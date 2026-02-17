from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd

from app.ml_uplift import UPLIFT_DATA_FILE
from app.ml_uplift.schema import UPLIFT_SAMPLE_COLUMNS


def _sample_file(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else UPLIFT_DATA_FILE


def ensure_sample_file(path: str | Path | None = None) -> Path:
    target = _sample_file(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=UPLIFT_SAMPLE_COLUMNS)
            writer.writeheader()
    return target


def append_samples(rows: list[dict[str, Any]], path: str | Path | None = None) -> int:
    if not rows:
        return 0

    target = ensure_sample_file(path)
    write_rows = []
    for row in rows:
        write_rows.append({name: row.get(name) for name in UPLIFT_SAMPLE_COLUMNS})

    with target.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=UPLIFT_SAMPLE_COLUMNS)
        writer.writerows(write_rows)
    return len(write_rows)


def read_samples_df(path: str | Path | None = None) -> pd.DataFrame:
    target = ensure_sample_file(path)
    return pd.read_csv(target)


def sample_count(path: str | Path | None = None) -> int:
    target = ensure_sample_file(path)
    try:
        df = pd.read_csv(target, usecols=["origin_lat"])
    except Exception:
        return 0
    return int(len(df))

