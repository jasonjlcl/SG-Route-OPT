from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.ml_uplift.features import build_uplift_inference_row, build_uplift_row, clamp_factor
from app.ml_uplift.model import load_uplift_artifact
from app.ml_uplift.storage import append_samples
from app.providers.google_routes import GoogleRouteLeg
from app.utils.settings import get_settings


LOGGER = logging.getLogger(__name__)


class MLUpliftService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._artifact_cache: dict[str, Any] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.feature_ml_uplift)

    def _load_artifact(self) -> dict[str, Any] | None:
        if self._artifact_cache is not None:
            return self._artifact_cache
        artifact = load_uplift_artifact()
        if artifact is None:
            return None
        self._artifact_cache = artifact
        return self._artifact_cache

    @property
    def model_version(self) -> str | None:
        artifact = self._load_artifact()
        if not artifact:
            return None
        return str(artifact.get("version") or "unknown")

    def model_available(self) -> bool:
        return self._load_artifact() is not None

    def predict_factors(self, feature_rows: list[dict[str, Any]]) -> list[float] | None:
        if not self.enabled:
            return None
        if not feature_rows:
            return []
        artifact = self._load_artifact()
        if not artifact:
            return None
        pipeline = artifact.get("pipeline")
        if pipeline is None:
            return None
        frame = pd.DataFrame(feature_rows)
        raw = pipeline.predict(frame)
        return [clamp_factor(float(value)) for value in raw]

    def build_inference_row(
        self,
        *,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        distance_m: float,
        departure_time_iso: str,
        static_duration_s: float,
    ) -> dict[str, Any]:
        return build_uplift_inference_row(
            origin_lat=origin_lat,
            origin_lng=origin_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            distance_m=distance_m,
            departure_time_iso=departure_time_iso,
            static_duration_s=static_duration_s,
        )

    def collect_google_leg_samples(
        self,
        *,
        route_points: list[dict[str, float]],
        leg_departure_isos: list[str],
        legs: list[GoogleRouteLeg],
    ) -> int:
        if len(route_points) < 2 or not legs:
            return 0
        if len(route_points) != len(legs) + 1:
            LOGGER.warning(
                "Skip uplift leg collection due to shape mismatch (points=%s, legs=%s)",
                len(route_points),
                len(legs),
            )
            return 0
        if len(leg_departure_isos) != len(legs):
            LOGGER.warning(
                "Skip uplift leg collection due to departure mismatch (departures=%s, legs=%s)",
                len(leg_departure_isos),
                len(legs),
            )
            return 0

        rows = []
        for idx, leg in enumerate(legs):
            origin = route_points[idx]
            destination = route_points[idx + 1]
            rows.append(
                build_uplift_row(
                    origin_lat=float(origin["lat"]),
                    origin_lng=float(origin["lon"]),
                    dest_lat=float(destination["lat"]),
                    dest_lng=float(destination["lon"]),
                    distance_m=float(leg.distance_m),
                    departure_time_iso=leg_departure_isos[idx],
                    static_duration_s=float(leg.static_duration_s),
                    duration_s=float(leg.duration_s),
                )
            )
        return append_samples(rows)


_UPLIFT_SERVICE: MLUpliftService | None = None


def get_ml_uplift_service() -> MLUpliftService:
    global _UPLIFT_SERVICE
    if _UPLIFT_SERVICE is None:
        _UPLIFT_SERVICE = MLUpliftService()
    return _UPLIFT_SERVICE

