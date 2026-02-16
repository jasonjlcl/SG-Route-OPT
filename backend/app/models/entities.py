from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="UPLOADED", nullable=False)

    stops: Mapped[list[Stop]] = relationship("Stop", back_populates="dataset", cascade="all, delete-orphan")
    plans: Mapped[list[Plan]] = relationship("Plan", back_populates="dataset", cascade="all, delete-orphan")
    error_logs: Mapped[list[ErrorLog]] = relationship("ErrorLog", back_populates="dataset", cascade="all, delete-orphan")


class Stop(Base):
    __tablename__ = "stops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    stop_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    demand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    service_time_min: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tw_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    tw_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    geocode_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    geocode_meta: Mapped[str | None] = mapped_column(Text, nullable=True)

    dataset: Mapped[Dataset] = relationship("Dataset", back_populates="stops")
    route_stops: Mapped[list[RouteStop]] = relationship("RouteStop", back_populates="stop")


class OdCache(Base):
    __tablename__ = "od_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    dest_lat: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    dest_lon: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    depart_bucket: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    base_distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    base_duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    predictions: Mapped[list[PredictionCache]] = relationship("PredictionCache", back_populates="od_cache", cascade="all, delete-orphan")


class PredictionCache(Base):
    __tablename__ = "predictions_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    od_cache_id: Mapped[int] = mapped_column(ForeignKey("od_cache.id", ondelete="CASCADE"), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    predicted_duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    od_cache: Mapped[OdCache] = relationship("OdCache", back_populates="predictions")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    depot_lat: Mapped[float] = mapped_column(Float, nullable=False)
    depot_lon: Mapped[float] = mapped_column(Float, nullable=False)
    num_vehicles: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    objective_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_makespan_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    vehicle_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workday_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    workday_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    infeasibility_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    dataset: Mapped[Dataset] = relationship("Dataset", back_populates="plans")
    routes: Mapped[list[Route]] = relationship("Route", back_populates="plan", cascade="all, delete-orphan")


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    total_distance_m: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    total_duration_s: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    plan: Mapped[Plan] = relationship("Plan", back_populates="routes")
    route_stops: Mapped[list[RouteStop]] = relationship("RouteStop", back_populates="route", cascade="all, delete-orphan")


class RouteStop(Base):
    __tablename__ = "route_stops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_id: Mapped[int | None] = mapped_column(ForeignKey("stops.id", ondelete="SET NULL"), nullable=True)
    eta_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    arrival_window_start_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    arrival_window_end_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_start_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_end_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)

    route: Mapped[Route] = relationship("Route", back_populates="route_stops")
    stop: Mapped[Stop | None] = relationship("Stop", back_populates="route_stops")


class ErrorLog(Base):
    __tablename__ = "error_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    dataset: Mapped[Dataset | None] = relationship("Dataset", back_populates="error_logs")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MLModel(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    feature_schema_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    training_data_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="TRAINED", index=True)


class ModelRollout(Base):
    __tablename__ = "model_rollouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    active_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canary_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canary_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PredictionLog(Base):
    __tablename__ = "prediction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lat: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lon: Mapped[float] = mapped_column(Float, nullable=False)
    features_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    predicted_duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    base_duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    request_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ActualTravelTime(Base):
    __tablename__ = "actual_travel_times"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lat: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lon: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp_iso: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actual_duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    route_id: Mapped[int | None] = mapped_column(ForeignKey("routes.id", ondelete="SET NULL"), nullable=True, index=True)
    stop_id: Mapped[int | None] = mapped_column(ForeignKey("stops.id", ondelete="SET NULL"), nullable=True, index=True)


class MLMonitoring(Base):
    __tablename__ = "ml_monitoring"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    drift_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    mape: Mapped[float | None] = mapped_column(Float, nullable=True)
    segmented_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_retrain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
