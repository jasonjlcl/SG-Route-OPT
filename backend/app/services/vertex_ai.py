from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.services.storage import upload_bytes
from app.utils.settings import get_settings

try:
    from google.cloud import aiplatform, storage

    VERTEX_AVAILABLE = True
except Exception:  # noqa: BLE001
    VERTEX_AVAILABLE = False


SKLEARN_SERVING_IMAGE = "us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-5:latest"


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
) -> list[float] | None:
    if not vertex_enabled() or not rows or not model_resource:
        return None

    settings = get_settings()
    bucket_name = (settings.gcs_bucket or "").replace("gs://", "").strip("/")
    if not bucket_name:
        return None

    # Vertex batch prediction will ignore unknown fields when using sklearn prebuilt
    # only if they are part of the serialized feature schema; row_id is used for join-back.
    input_lines = []
    for idx, row in enumerate(rows):
        line = {"row_id": idx, **row}
        input_lines.append(json.dumps(line))
    input_bytes = ("\n".join(input_lines) + "\n").encode("utf-8")

    input_ref = upload_bytes(
        object_path=f"vertex/batch_inputs/{job_key}.jsonl",
        payload=input_bytes,
        content_type="application/jsonl",
    )
    input_uri = input_ref.get("gcs_uri")
    if not input_uri:
        return None

    output_prefix = f"gs://{bucket_name}/vertex/batch_outputs/{job_key}"
    job_display_name = f"route-matrix-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    try:
        aiplatform.init(project=settings.gcp_project_id, location=settings.gcp_region)
        batch_job = aiplatform.BatchPredictionJob.create(
            job_display_name=job_display_name,
            model_name=model_resource,
            gcs_source=input_uri,
            instances_format="jsonl",
            gcs_destination_prefix=output_prefix,
            predictions_format="jsonl",
            sync=True,
        )
    except Exception:
        return None

    try:
        prefix = batch_job.output_info.gcs_output_directory.replace(f"gs://{bucket_name}/", "").strip("/")
        client = storage.Client(project=settings.gcp_project_id)
        blobs = list(client.list_blobs(bucket_name, prefix=prefix))
        predictions: dict[int, float] = {}
        for blob in blobs:
            if not blob.name.endswith(".jsonl"):
                continue
            content = blob.download_as_text(encoding="utf-8")
            for line in content.splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                row_id = int(payload.get("instance", {}).get("row_id", payload.get("row_id", -1)))
                pred_raw = payload.get("prediction", payload.get("predictions"))
                value: float | None = None
                if isinstance(pred_raw, list) and pred_raw:
                    value = float(pred_raw[0])
                elif isinstance(pred_raw, (int, float)):
                    value = float(pred_raw)
                if value is not None and row_id >= 0:
                    predictions[row_id] = value

        if len(predictions) != len(rows):
            return None
        return [float(predictions[idx]) for idx in range(len(rows))]
    except Exception:
        return None
