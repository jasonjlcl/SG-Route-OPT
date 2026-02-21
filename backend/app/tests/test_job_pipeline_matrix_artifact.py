import pytest

from app.services import job_pipeline
from app.utils.errors import AppError


def test_load_matrix_artifact_prefers_object_path(monkeypatch):
    monkeypatch.setattr(
        job_pipeline,
        "download_bytes",
        lambda *, object_path: b'{"source":"object_path","object_path":"' + object_path.encode("utf-8") + b'"}',
    )
    monkeypatch.setattr(
        job_pipeline,
        "load_matrix_artifact",
        lambda _path: pytest.fail("load_matrix_artifact should not be used when object_path is readable"),
    )

    result = job_pipeline._load_matrix_artifact_for_optimize(
        result_ref={
            "matrix_artifact_ref": {"object_path": "matrix/job-1.json"},
            "matrix_artifact_path": "C:/tmp/fallback.json",
        }
    )

    assert result["source"] == "object_path"
    assert result["object_path"] == "matrix/job-1.json"


def test_load_matrix_artifact_falls_back_to_matrix_path(monkeypatch):
    monkeypatch.setattr(job_pipeline, "download_bytes", lambda *, object_path: None)

    seen: dict[str, str] = {}

    def _fake_load(path: str) -> dict[str, str]:
        seen["path"] = path
        return {"source": "matrix_path"}

    monkeypatch.setattr(job_pipeline, "load_matrix_artifact", _fake_load)

    result = job_pipeline._load_matrix_artifact_for_optimize(
        result_ref={
            "matrix_artifact_ref": {"object_path": "matrix/job-2.json"},
            "matrix_artifact_path": "C:/tmp/fallback.json",
        }
    )

    assert result["source"] == "matrix_path"
    assert seen["path"] == "C:/tmp/fallback.json"


def test_load_matrix_artifact_raises_when_missing_refs():
    with pytest.raises(AppError) as exc:
        job_pipeline._load_matrix_artifact_for_optimize(result_ref={})

    assert exc.value.error_code == "MATRIX_ARTIFACT_MISSING"
