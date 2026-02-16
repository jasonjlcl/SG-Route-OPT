from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from app.utils.settings import get_settings

try:
    from google.cloud import storage

    STORAGE_AVAILABLE = True
except Exception:  # noqa: BLE001
    STORAGE_AVAILABLE = False


LOCAL_ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "cache" / "artifacts"
LOCAL_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _bucket_name() -> str | None:
    bucket = get_settings().gcs_bucket
    if not bucket:
        return None
    return bucket.replace("gs://", "").strip("/")


def gcs_enabled() -> bool:
    return STORAGE_AVAILABLE and bool(_bucket_name())


def upload_bytes(
    *,
    object_path: str,
    payload: bytes,
    content_type: str | None = None,
) -> dict[str, Any]:
    bucket_name = _bucket_name()
    clean_path = object_path.lstrip("/")
    if gcs_enabled() and bucket_name:
        client = storage.Client(project=get_settings().gcp_project_id or None)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(clean_path)
        blob.upload_from_string(payload, content_type=content_type)
        return {
            "storage": "gcs",
            "gcs_uri": f"gs://{bucket_name}/{clean_path}",
            "object_path": clean_path,
        }

    target = LOCAL_ARTIFACT_DIR / clean_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {
        "storage": "local",
        "file_path": str(target),
        "object_path": clean_path,
    }


def signed_download_url(*, object_path: str) -> str | None:
    bucket_name = _bucket_name()
    if gcs_enabled() and bucket_name:
        client = storage.Client(project=get_settings().gcp_project_id or None)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_path.lstrip("/"))
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=max(300, int(get_settings().signed_url_ttl_seconds))),
            method="GET",
        )
    return None
