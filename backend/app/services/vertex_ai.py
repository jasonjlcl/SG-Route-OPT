from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.ml_features import FEATURE_COLUMNS
from app.services.storage import upload_bytes
from app.utils.settings import get_settings

try:
    from google.cloud import aiplatform, aiplatform_v1, storage

    VERTEX_AVAILABLE = True
except Exception:  # noqa: BLE001
    VERTEX_AVAILABLE = False


SKLEARN_SERVING_IMAGE = "us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-5:latest"
LOGGER = logging.getLogger(__name__)
TERMINAL_BATCH_STATES = {
    "JOB_STATE_SUCCEEDED",
    "JOB_STATE_FAILED",
    "JOB_STATE_CANCELLED",
    "JOB_STATE_PAUSED",
    "JOB_STATE_EXPIRED",
}


@dataclass
class VertexBatchPredictionResult:
    predictions: list[float] | None
    reason: str
    job_name: str | None = None
    state: str | None = None
    output_directory: str | None = None


def _job_state_name(state: Any) -> str:
    try:
        return aiplatform_v1.types.JobState(state).name
    except Exception:  # noqa: BLE001
        return str(state)


def _split_gcs_uri(uri: str | None) -> tuple[str, str] | None:
    text = str(uri or "").strip()
    if not text.startswith("gs://"):
        return None
    without_scheme = text[5:]
    if "/" not in without_scheme:
        return None
    bucket_name, object_path = without_scheme.split("/", 1)
    clean_bucket = bucket_name.strip("/")
    clean_path = object_path.strip("/")
    if not clean_bucket or not clean_path:
        return None
    return clean_bucket, clean_path


def _coerce_row_id(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def _coerce_prediction_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    if isinstance(value, list):
        if not value:
            return None
        return _coerce_prediction_value(value[0])
    if isinstance(value, dict):
        for key in ("value", "values", "prediction", "predictions", "score"):
            if key in value:
                parsed = _coerce_prediction_value(value.get(key))
                if parsed is not None:
                    return parsed
        if len(value) == 1:
            return _coerce_prediction_value(next(iter(value.values())))
    return None


def _extract_prediction_record(payload: Any) -> tuple[int | None, float | None]:
    row_id: int | None = None
    pred_raw: Any = payload

    if isinstance(payload, dict):
        row_id = _coerce_row_id(payload.get("row_id"))
        if row_id is None:
            instance = payload.get("instance")
            if isinstance(instance, dict):
                row_id = _coerce_row_id(instance.get("row_id"))

        pred_raw = payload.get("prediction")
        if pred_raw is None:
            pred_raw = payload.get("predictions")
        if pred_raw is None:
            pred_raw = payload.get("score")

    return row_id, _coerce_prediction_value(pred_raw)


def _serialize_feature_row(row: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for column in FEATURE_COLUMNS:
        raw = row.get(column)
        try:
            values.append(float(raw))
        except Exception:  # noqa: BLE001
            values.append(0.0)
    return values


def _jsonl_prediction_blobs(client: Any, *, bucket_name: str, prefix: str) -> list[Any]:
    blobs = sorted(client.list_blobs(bucket_name, prefix=prefix), key=lambda item: item.name)
    prediction_files = [blob for blob in blobs if "prediction.results" in blob.name.lower()]
    if prediction_files:
        return prediction_files
    prediction_files = [
        blob
        for blob in blobs
        if blob.name.endswith(".jsonl") and "error" not in blob.name.lower()
    ]
    if prediction_files:
        return prediction_files
    return [
        blob
        for blob in blobs
        if "prediction" in blob.name.lower() and "error" not in blob.name.lower()
    ]


def vertex_enabled() -> bool:
    settings = get_settings()
    return bool(
        settings.feature_vertex_ai
        and VERTEX_AVAILABLE
        and settings.gcp_project_id
        and settings.gcp_region
        and settings.gcs_bucket
    )


def register_local_model_to_vertex(*, model_version: str, model_bytes: bytes) -> dict[str, str] | None:
    if not vertex_enabled():
        return None

    settings = get_settings()
    bucket_name = (settings.gcs_bucket or "").replace("gs://", "").strip("/")
    if not bucket_name:
        return None

    uploaded = upload_bytes(
        object_path=f"models/{model_version}/model.joblib",
        payload=model_bytes,
        content_type="application/octet-stream",
    )
    artifact_gcs_uri = uploaded.get("gcs_uri")
    if not artifact_gcs_uri:
        return None

    aiplatform.init(project=settings.gcp_project_id, location=settings.gcp_region)
    model = aiplatform.Model.upload(
        display_name=settings.vertex_model_display_name,
        artifact_uri=f"gs://{bucket_name}/models/{model_version}",
        serving_container_image_uri=SKLEARN_SERVING_IMAGE,
        sync=True,
    )
    return {
        "artifact_gcs_uri": artifact_gcs_uri,
        "vertex_model_resource": model.resource_name,
    }


def run_vertex_batch_prediction(
    *,
    model_resource: str,
    rows: list[dict[str, Any]],
    job_key: str,
) -> VertexBatchPredictionResult:
    if not vertex_enabled():
        return VertexBatchPredictionResult(predictions=None, reason="vertex_disabled")
    if not rows:
        return VertexBatchPredictionResult(predictions=None, reason="empty_rows")
    if not model_resource:
        return VertexBatchPredictionResult(predictions=None, reason="missing_model_resource")

    settings = get_settings()
    bucket_name = (settings.gcs_bucket or "").replace("gs://", "").strip("/")
    if not bucket_name:
        return VertexBatchPredictionResult(predictions=None, reason="missing_bucket")

    # For sklearn prebuilt prediction, instances must be numeric arrays aligned with training schema.
    input_lines = []
    for row in rows:
        line = _serialize_feature_row(row)
        input_lines.append(json.dumps(line))
    input_bytes = ("\n".join(input_lines) + "\n").encode("utf-8")

    input_ref = upload_bytes(
        object_path=f"vertex/batch_inputs/{job_key}.jsonl",
        payload=input_bytes,
        content_type="application/jsonl",
    )
    input_uri = input_ref.get("gcs_uri")
    if not input_uri:
        return VertexBatchPredictionResult(predictions=None, reason="input_upload_failed")

    output_prefix = f"gs://{bucket_name}/vertex/batch_outputs/{job_key}"
    job_display_name = f"route-matrix-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    job_name = None
    try:
        endpoint = f"{settings.gcp_region}-aiplatform.googleapis.com"
        job_client = aiplatform_v1.JobServiceClient(client_options={"api_endpoint": endpoint})
        parent = f"projects/{settings.gcp_project_id}/locations/{settings.gcp_region}"
        created_job = job_client.create_batch_prediction_job(
            parent=parent,
            batch_prediction_job={
                "display_name": job_display_name,
                "model": model_resource,
                "input_config": {
                    "instances_format": "jsonl",
                    "gcs_source": {"uris": [input_uri]},
                },
                "output_config": {
                    "predictions_format": "jsonl",
                    "gcs_destination": {"output_uri_prefix": output_prefix},
                },
                "dedicated_resources": {
                    "machine_spec": {"machine_type": settings.vertex_batch_machine_type},
                    "starting_replica_count": int(settings.vertex_batch_starting_replica_count),
                    "max_replica_count": int(settings.vertex_batch_max_replica_count),
                },
            },
        )
        job_name = str(created_job.name)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Vertex batch prediction job creation failed: %s", exc)
        return VertexBatchPredictionResult(predictions=None, reason="job_creation_failed", job_name=job_name)

    try:
        deadline = time.monotonic() + int(settings.vertex_batch_timeout_seconds)
        poll_s = max(1, int(settings.vertex_batch_poll_interval_seconds))
        batch_info = None
        state_name = "UNKNOWN"

        while time.monotonic() < deadline:
            batch_info = job_client.get_batch_prediction_job(name=job_name)
            state_name = _job_state_name(batch_info.state)
            if state_name == "JOB_STATE_SUCCEEDED":
                break
            if state_name in TERMINAL_BATCH_STATES:
                LOGGER.warning("Vertex batch prediction finished without success: job=%s state=%s", job_name, state_name)
                return VertexBatchPredictionResult(
                    predictions=None,
                    reason=f"job_{state_name.lower()}",
                    job_name=job_name,
                    state=state_name,
                )
            time.sleep(poll_s)

        if batch_info is None or _job_state_name(batch_info.state) != "JOB_STATE_SUCCEEDED":
            try:
                job_client.cancel_batch_prediction_job(name=job_name)
            except Exception:  # noqa: BLE001
                pass
            LOGGER.warning(
                "Vertex batch prediction timed out: job=%s state=%s timeout_s=%s",
                job_name,
                state_name,
                settings.vertex_batch_timeout_seconds,
            )
            return VertexBatchPredictionResult(
                predictions=None,
                reason="job_timeout",
                job_name=job_name,
                state=state_name,
            )

        output_directory = str(batch_info.output_info.gcs_output_directory or "").strip()
        if not output_directory:
            LOGGER.warning("Vertex batch prediction missing output directory: job=%s", job_name)
            return VertexBatchPredictionResult(
                predictions=None,
                reason="missing_output_directory",
                job_name=job_name,
                state="JOB_STATE_SUCCEEDED",
            )

        output_target = _split_gcs_uri(output_directory)
        if output_target is None:
            LOGGER.warning("Vertex batch prediction output directory format invalid: job=%s value=%s", job_name, output_directory)
            return VertexBatchPredictionResult(
                predictions=None,
                reason="invalid_output_directory",
                job_name=job_name,
                state="JOB_STATE_SUCCEEDED",
                output_directory=output_directory,
            )

        output_bucket, output_prefix_path = output_target
        client = storage.Client(project=settings.gcp_project_id)
        settle_deadline = time.monotonic() + max(0, int(settings.vertex_batch_output_wait_seconds))
        blobs = _jsonl_prediction_blobs(client, bucket_name=output_bucket, prefix=output_prefix_path)
        while not blobs and time.monotonic() < settle_deadline:
            time.sleep(min(2, poll_s))
            blobs = _jsonl_prediction_blobs(client, bucket_name=output_bucket, prefix=output_prefix_path)
        if not blobs:
            LOGGER.warning(
                "Vertex batch prediction output files not ready: job=%s output_directory=%s wait_s=%s",
                job_name,
                output_directory,
                settings.vertex_batch_output_wait_seconds,
            )
            return VertexBatchPredictionResult(
                predictions=None,
                reason="output_not_ready",
                job_name=job_name,
                state="JOB_STATE_SUCCEEDED",
                output_directory=output_directory,
            )

        predictions: dict[int, float] = {}
        next_unkeyed_row_id = 0
        for blob in blobs:
            content = blob.download_as_text(encoding="utf-8")
            for line in content.splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                row_id, value = _extract_prediction_record(payload)

                if value is not None and row_id is None:
                    while next_unkeyed_row_id in predictions and next_unkeyed_row_id < len(rows):
                        next_unkeyed_row_id += 1
                    row_id = next_unkeyed_row_id
                    next_unkeyed_row_id += 1

                if value is not None and row_id is not None and 0 <= row_id < len(rows):
                    predictions[row_id] = value

        if len(predictions) != len(rows):
            LOGGER.warning(
                "Vertex batch prediction row mismatch: expected=%s actual=%s output_prefix=%s",
                len(rows),
                len(predictions),
                output_prefix_path,
            )
            return VertexBatchPredictionResult(
                predictions=None,
                reason="row_mismatch",
                job_name=job_name,
                state="JOB_STATE_SUCCEEDED",
                output_directory=output_directory,
            )
        return VertexBatchPredictionResult(
            predictions=[float(predictions[idx]) for idx in range(len(rows))],
            reason="success",
            job_name=job_name,
            state="JOB_STATE_SUCCEEDED",
            output_directory=output_directory,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Vertex batch prediction result read failed: %s", exc)
        return VertexBatchPredictionResult(predictions=None, reason="result_read_failed", job_name=job_name)
