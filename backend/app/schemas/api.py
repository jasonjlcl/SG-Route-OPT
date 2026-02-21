from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ValidationIssueOut(BaseModel):
    row_index: int
    reason: str


class ValidationSummaryOut(BaseModel):
    valid_rows_count: int
    invalid_rows_count: int
    invalid_rows: list[ValidationIssueOut]


class DatasetUploadResponse(BaseModel):
    dataset_id: int
    validation_summary: ValidationSummaryOut
    next_action: str


class DatasetSummaryResponse(BaseModel):
    id: int
    filename: str
    created_at: str
    status: str
    stop_count: int
    valid_stop_count: int
    geocode_counts: dict[str, int]
    validation_state: Literal["NOT_STARTED", "BLOCKED", "PARTIAL", "VALID"]
    geocode_state: Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETE", "NEEDS_ATTENTION"]
    optimize_state: Literal["NOT_STARTED", "RUNNING", "COMPLETE", "NEEDS_ATTENTION"]
    latest_plan_id: int | None = None
    latest_plan_status: str | None = None


class StopOut(BaseModel):
    id: int
    stop_ref: str
    address: str | None
    postal_code: str | None
    lat: float | None
    lon: float | None
    demand: int
    service_time_min: int
    tw_start: str | None
    tw_end: str | None
    phone: str | None = None
    contact_name: str | None = None
    geocode_status: str
    geocode_meta: str | None


class StopsPageResponse(BaseModel):
    items: list[StopOut]
    page: int
    page_size: int
    total: int


class ManualGeocodeRequest(BaseModel):
    corrected_address: str | None = None
    corrected_postal_code: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def ensure_payload(self) -> "ManualGeocodeRequest":
        has_pin = self.lat is not None and self.lon is not None
        has_query = bool(self.corrected_address or self.corrected_postal_code)
        if not has_pin and not has_query:
            raise ValueError("Provide corrected address/postal code or lat/lon")
        return self


class FleetConfig(BaseModel):
    num_vehicles: int = Field(gt=0)
    capacity: int | None = Field(default=None, gt=0)


class SolverConfig(BaseModel):
    solver_time_limit_s: int = Field(default=15, ge=5, le=120)
    allow_drop_visits: bool = False


def _validate_workday_fields(workday_start: str, workday_end: str) -> tuple[str, str]:
    try:
        start_dt = datetime.strptime(str(workday_start), "%H:%M")
        end_dt = datetime.strptime(str(workday_end), "%H:%M")
    except ValueError as exc:
        raise ValueError("workday_start/workday_end must be HH:MM (24-hour)") from exc

    if start_dt >= end_dt:
        raise ValueError("workday_start must be earlier than workday_end")

    return start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M")


class OptimizeRequest(BaseModel):
    depot_lat: float = Field(ge=-90, le=90)
    depot_lon: float = Field(ge=-180, le=180)
    fleet: FleetConfig
    workday_start: str = "08:00"
    workday_end: str = "18:00"
    solver: SolverConfig = SolverConfig()
    use_live_traffic: bool = False

    @model_validator(mode="after")
    def ensure_workday_window(self) -> "OptimizeRequest":
        self.workday_start, self.workday_end = _validate_workday_fields(self.workday_start, self.workday_end)
        return self


class OptimizeExperimentRequest(OptimizeRequest):
    model_version: str | None = None


class OptimizeJobRequest(BaseModel):
    dataset_id: int = Field(gt=0)
    depot_lat: float = Field(ge=-90, le=90)
    depot_lon: float = Field(ge=-180, le=180)
    fleet_config: FleetConfig
    workday_start: str = "08:00"
    workday_end: str = "18:00"
    solver: SolverConfig = SolverConfig()
    use_live_traffic: bool = False

    @model_validator(mode="after")
    def ensure_workday_window(self) -> "OptimizeJobRequest":
        self.workday_start, self.workday_end = _validate_workday_fields(self.workday_start, self.workday_end)
        return self


class EvaluationRunRequest(BaseModel):
    dataset_id: int = Field(gt=0)
    depot_lat: float = Field(ge=-90, le=90)
    depot_lon: float = Field(ge=-180, le=180)
    fleet_config: FleetConfig
    workday_start: str = "08:00"
    workday_end: str = "18:00"
    solver: SolverConfig = SolverConfig()
    sample_limit: int = Field(default=5000, ge=100, le=100000)

    @model_validator(mode="after")
    def ensure_workday_window(self) -> "EvaluationRunRequest":
        self.workday_start, self.workday_end = _validate_workday_fields(self.workday_start, self.workday_end)
        return self


class OptimizeResponse(BaseModel):
    plan_id: int
    feasible: bool
    status: str | None = None
    objective_value: float | None = None
    total_makespan_s: float | None = None
    sum_vehicle_durations_s: float | None = None
    route_summary: list[dict[str, Any]] | None = None
    unserved_stop_ids: list[int] | None = None
    infeasibility_reason: str | None = None
    suggestions: list[str] | None = None
    eta_source: Literal["google_traffic", "ml_uplift", "ml_baseline", "onemap"] | None = None
    traffic_timestamp: str | None = None
    live_traffic_requested: bool | None = None
    warnings: list[str] | None = None


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str = "QUEUED"
    type: str


class JobStatusResponse(BaseModel):
    job_id: str
    type: str
    status: str
    progress: int
    progress_pct: int | None = None
    current_step: str | None = None
    message: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    steps: dict[str, Any] | None = None
    result_ref: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class ResequenceRequest(BaseModel):
    ordered_stop_ids: list[int]
    depart_time_iso: str | None = None
    apply: bool = False
    use_live_traffic: bool | None = None


class PlanDetailsResponse(BaseModel):
    plan_id: int
    dataset_id: int
    status: str
    objective_value: float
    total_makespan_s: float | None = None
    sum_vehicle_durations_s: float
    infeasibility_reason: str | None
    depot: dict[str, float]
    routes: list[dict[str, Any]]
    unserved_stops: list[dict[str, Any]]
    eta_source: Literal["google_traffic", "ml_uplift", "ml_baseline", "onemap"] | None = None
    traffic_timestamp: str | None = None
    live_traffic_requested: bool = False


class ExportFormat(str):
    CSV = "csv"
    PDF = "pdf"


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: Any
    correlation_id: str
