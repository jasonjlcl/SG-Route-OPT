from __future__ import annotations

from pathlib import Path


REPO_BACKEND_DIR = Path(__file__).resolve().parents[2]
UPLIFT_DATA_DIR = REPO_BACKEND_DIR / "data" / "ml_uplift"
UPLIFT_DATA_FILE = UPLIFT_DATA_DIR / "samples.csv"
UPLIFT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

UPLIFT_DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLIFT_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

