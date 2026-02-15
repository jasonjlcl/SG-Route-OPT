from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, Text
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
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    objective_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
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
