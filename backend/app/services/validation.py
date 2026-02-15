from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from app.utils.errors import AppError

REQUIRED_BASE_COL = "stop_ref"
OPTIONAL_COLS = ["address", "postal_code", "demand", "service_time_min", "tw_start", "tw_end"]
ALL_COLS = [REQUIRED_BASE_COL] + OPTIONAL_COLS


@dataclass
class ValidationIssue:
    row_index: int
    reason: str


@dataclass
class ValidationResult:
    valid_rows: list[dict[str, Any]]
    invalid_rows: list[ValidationIssue]

    @property
    def valid_rows_count(self) -> int:
        return len(self.valid_rows)

    @property
    def invalid_rows_count(self) -> int:
        return len(self.invalid_rows)


def parse_uploaded_file(filename: str, content: bytes) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content))
    if lower.endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(content), engine="openpyxl")
    raise AppError(
        message="Unsupported file type. Upload CSV or XLSX.",
        error_code="UNSUPPORTED_FILE",
        status_code=400,
        stage="VALIDATION",
    )


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {}
    for col in df.columns:
        normalized = str(col).strip().lower()
        renamed[col] = normalized
    out = df.rename(columns=renamed)

    for col in ALL_COLS:
        if col not in out.columns:
            out[col] = None

    return out


def _parse_time(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%H:%M")
        return dt.strftime("%H:%M")
    except ValueError:
        return None


def validate_rows(df: pd.DataFrame) -> ValidationResult:
    normalized_raw = df.rename(columns={col: str(col).strip().lower() for col in df.columns})

    if REQUIRED_BASE_COL not in normalized_raw.columns:
        raise AppError(
            message="Missing required column: stop_ref",
            error_code="MISSING_COLUMNS",
            status_code=400,
            stage="VALIDATION",
        )

    if "address" not in normalized_raw.columns and "postal_code" not in normalized_raw.columns:
        raise AppError(
            message="File must include at least one of address or postal_code columns.",
            error_code="MISSING_COLUMNS",
            status_code=400,
            stage="VALIDATION",
        )

    normalized = normalize_columns(df)

    valid_rows: list[dict[str, Any]] = []
    invalid_rows: list[ValidationIssue] = []

    for idx, row in normalized.iterrows():
        row_idx = int(idx) + 2
        reasons: list[str] = []

        stop_ref = str(row.get("stop_ref") or "").strip()
        if not stop_ref:
            reasons.append("stop_ref is required")

        address = str(row.get("address") or "").strip()
        postal_code = str(row.get("postal_code") or "").strip()
        if not address and not postal_code:
            reasons.append("address or postal_code is required")

        demand = row.get("demand", 0)
        service_time_min = row.get("service_time_min", 0)

        try:
            demand = int(0 if pd.isna(demand) else demand)
        except (ValueError, TypeError):
            reasons.append("demand must be an integer")
            demand = 0

        try:
            service_time_min = int(0 if pd.isna(service_time_min) else service_time_min)
        except (ValueError, TypeError):
            reasons.append("service_time_min must be an integer")
            service_time_min = 0

        if demand < 0:
            reasons.append("demand must be non-negative")
        if service_time_min < 0:
            reasons.append("service_time_min must be non-negative")

        tw_start = _parse_time(row.get("tw_start"))
        tw_end = _parse_time(row.get("tw_end"))

        if row.get("tw_start") not in (None, "") and tw_start is None:
            reasons.append("tw_start must be HH:MM")
        if row.get("tw_end") not in (None, "") and tw_end is None:
            reasons.append("tw_end must be HH:MM")

        if tw_start and tw_end and tw_start >= tw_end:
            reasons.append("tw_start must be earlier than tw_end")

        if reasons:
            invalid_rows.append(ValidationIssue(row_index=row_idx, reason="; ".join(reasons)))
            continue

        valid_rows.append(
            {
                "stop_ref": stop_ref,
                "address": address or None,
                "postal_code": postal_code or None,
                "demand": demand,
                "service_time_min": service_time_min,
                "tw_start": tw_start,
                "tw_end": tw_end,
            }
        )

    return ValidationResult(valid_rows=valid_rows, invalid_rows=invalid_rows)


def build_error_log_csv(issues: list[ValidationIssue]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["row_index", "reason"])
    for item in issues:
        writer.writerow([item.row_index, item.reason])
    return output.getvalue()
