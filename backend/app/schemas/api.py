from __future__ import annotations

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
    geocode_counts: dict[str, int]


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
    lat: float | None = None
    lon: float | None = None

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


class OptimizeRequest(BaseModel):
    depot_lat: float
    depot_lon: float
    fleet: FleetConfig
    workday_start: str = "08:00"
    workday_end: str = "18:00"
    solver: SolverConfig = SolverConfig()


class OptimizeResponse(BaseModel):
    plan_id: int
    feasible: bool
    status: str | None = None
    objective_value: float | None = None
    route_summary: list[dict[str, Any]] | None = None
    unserved_stop_ids: list[int] | None = None
    infeasibility_reason: str | None = None
    suggestions: list[str] | None = None


class PlanDetailsResponse(BaseModel):
    plan_id: int
    dataset_id: int
    status: str
    objective_value: float
    infeasibility_reason: str | None
    depot: dict[str, float]
    routes: list[dict[str, Any]]
    unserved_stops: list[dict[str, Any]]


class ExportFormat(str):
    CSV = "csv"
    PDF = "pdf"


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: Any
    correlation_id: str
