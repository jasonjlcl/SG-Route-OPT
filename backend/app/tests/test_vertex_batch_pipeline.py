from types import SimpleNamespace

from app.services import job_pipeline
from app.services.ml_features import FEATURE_COLUMNS
from app.services import vertex_ai


def _artifact_fixture() -> dict:
    return {
        "nodes": [
            {"lat": 1.30, "lon": 103.80},
            {"lat": 1.31, "lon": 103.81},
        ],
        "distance_matrix_m": [
            [0.0, 1000.0],
            [1100.0, 0.0],
        ],
        "base_duration_matrix_s": [
            [0.0, 120.0],
            [130.0, 0.0],
        ],
        "duration_matrix_s": [
            [0, 120],
            [130, 0],
        ],
        "depart_bucket": "08:00",
        "day_of_week": 1,
    }


def test_vertex_batch_override_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        job_pipeline,
        "get_settings",
        lambda: SimpleNamespace(feature_vertex_ai=True, feature_vertex_batch_override=False),
    )

    result = job_pipeline._apply_vertex_batch_if_enabled(db=object(), job_id="job-1", artifact=_artifact_fixture())

    assert result["vertex_batch_used"] is False
    assert result["reason"] == "batch_override_disabled"


def test_vertex_batch_propagates_unavailable_reason(monkeypatch):
    monkeypatch.setattr(
        job_pipeline,
        "get_settings",
        lambda: SimpleNamespace(feature_vertex_ai=True, feature_vertex_batch_override=True),
    )
    monkeypatch.setattr(job_pipeline, "get_latest_rollout", lambda _db: {"active_version": "v1"})
    monkeypatch.setattr(job_pipeline, "get_model_metadata", lambda _db, _v: {"vertex_model_resource": "projects/p/locations/l/models/1"})
    monkeypatch.setattr(
        job_pipeline,
        "run_vertex_batch_prediction",
        lambda **_kwargs: vertex_ai.VertexBatchPredictionResult(
            predictions=None,
            reason="job_timeout",
            job_name="projects/p/locations/l/batchPredictionJobs/99",
            state="JOB_STATE_RUNNING",
        ),
    )

    result = job_pipeline._apply_vertex_batch_if_enabled(db=object(), job_id="job-2", artifact=_artifact_fixture())

    assert result["vertex_batch_used"] is False
    assert result["reason"] == "job_timeout"
    assert result["job_name"].endswith("/99")
    assert result["state"] == "JOB_STATE_RUNNING"


def test_vertex_batch_success_updates_duration_matrix(monkeypatch):
    artifact = _artifact_fixture()
    monkeypatch.setattr(
        job_pipeline,
        "get_settings",
        lambda: SimpleNamespace(feature_vertex_ai=True, feature_vertex_batch_override=True),
    )
    monkeypatch.setattr(job_pipeline, "get_latest_rollout", lambda _db: {"active_version": "v2026"})
    monkeypatch.setattr(
        job_pipeline,
        "get_model_metadata",
        lambda _db, _v: {"vertex_model_resource": "projects/p/locations/l/models/2"},
    )
    monkeypatch.setattr(
        job_pipeline,
        "run_vertex_batch_prediction",
        lambda **_kwargs: vertex_ai.VertexBatchPredictionResult(
            predictions=[151.2, 241.6],
            reason="success",
            job_name="projects/p/locations/l/batchPredictionJobs/100",
            state="JOB_STATE_SUCCEEDED",
        ),
    )

    result = job_pipeline._apply_vertex_batch_if_enabled(db=object(), job_id="job-3", artifact=artifact)

    assert result["vertex_batch_used"] is True
    assert result["model_version"] == "v2026"
    assert artifact["duration_matrix_s"][0][1] == 151
    assert artifact["duration_matrix_s"][1][0] == 242
    assert artifact["vertex_batch_used"] is True
    assert artifact["vertex_batch_job_name"].endswith("/100")


def test_vertex_helpers_parse_nested_prediction_shapes():
    assert vertex_ai._coerce_row_id("7.0") == 7
    assert vertex_ai._coerce_row_id("not-a-number") is None
    assert vertex_ai._coerce_prediction_value([[123.4]]) == 123.4
    assert vertex_ai._coerce_prediction_value({"value": [["88.5"]]}) == 88.5
    assert vertex_ai._split_gcs_uri("gs://route_app/path/to/output/") == ("route_app", "path/to/output")
    assert vertex_ai._extract_prediction_record({"row_id": "3", "prediction": "77.7"}) == (3, 77.7)
    assert vertex_ai._extract_prediction_record({"instance": {"row_id": "4"}, "prediction": 12}) == (4, 12.0)
    assert vertex_ai._extract_prediction_record({"instance": [1, 2, 3], "prediction": 99.0}) == (None, 99.0)
    assert vertex_ai._extract_prediction_record([123.45]) == (None, 123.45)


def test_vertex_serialize_feature_row_aligns_to_schema():
    row = {"base_duration_s": "100", "distance_m": 1200, "hour": "bad-value"}
    serialized = vertex_ai._serialize_feature_row(row)
    assert len(serialized) == len(FEATURE_COLUMNS)
    assert serialized[FEATURE_COLUMNS.index("base_duration_s")] == 100.0
    assert serialized[FEATURE_COLUMNS.index("distance_m")] == 1200.0
    assert serialized[FEATURE_COLUMNS.index("hour")] == 0.0


def test_vertex_output_blob_selector_handles_prediction_results():
    class _Blob:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Client:
        def list_blobs(self, _bucket: str, prefix: str):
            assert prefix == "vertex/batch_outputs/job-1/prediction-run-1"
            return [
                _Blob("vertex/batch_outputs/job-1/prediction-run-1/prediction.errors_stats-00000-of-00001"),
                _Blob("vertex/batch_outputs/job-1/prediction-run-1/prediction.results-00000-of-00001"),
            ]

    blobs = vertex_ai._jsonl_prediction_blobs(
        _Client(),
        bucket_name="route_app",
        prefix="vertex/batch_outputs/job-1/prediction-run-1",
    )
    assert [blob.name for blob in blobs] == [
        "vertex/batch_outputs/job-1/prediction-run-1/prediction.results-00000-of-00001"
    ]


def test_vertex_read_prediction_outputs_handles_instance_arrays():
    class _Blob:
        def __init__(self, name: str, payload: str) -> None:
            self.name = name
            self._payload = payload

        def download_as_text(self, encoding: str = "utf-8") -> str:  # noqa: ARG002
            return self._payload

    class _Client:
        def list_blobs(self, _bucket: str, prefix: str):
            assert prefix == "vertex/batch_outputs/job-1/prediction-run-1"
            return [
                _Blob(
                    "vertex/batch_outputs/job-1/prediction-run-1/prediction.results-00000-of-00001",
                    '{"instance":[1.0,2.0],"prediction":111.5}\n{"instance":[3.0,4.0],"prediction":222.5}\n',
                ),
            ]

    predictions, reason, parsed_count = vertex_ai._read_prediction_outputs(
        client=_Client(),
        bucket_name="route_app",
        prefix_path="vertex/batch_outputs/job-1/prediction-run-1",
        rows=[{"a": 1}, {"a": 2}],
        poll_s=1,
        wait_seconds=0,
    )

    assert reason == "success"
    assert parsed_count == 2
    assert predictions == [111.5, 222.5]
