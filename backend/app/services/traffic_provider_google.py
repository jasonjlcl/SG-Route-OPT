from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.providers.google_routes import (
    GoogleMatrixElement,
    GoogleRouteLeg,
    GoogleRoutesError,
    get_google_routes_provider,
    parse_google_duration_seconds,
)


@dataclass
class ParsedGoogleRoute:
    durations_s: list[int]
    distances_m: list[float]
    static_durations_s: list[int]
    polyline: str | None = None


GoogleTrafficError = GoogleRoutesError


def parse_google_routes_response(payload: dict[str, Any], *, expected_legs: int | None = None) -> ParsedGoogleRoute:
    parsed = get_google_routes_provider().parse_compute_routes_payload(payload, expected_legs=expected_legs)
    return ParsedGoogleRoute(
        durations_s=[max(1, int(leg.duration_s)) for leg in parsed.legs],
        distances_m=[float(leg.distance_m) for leg in parsed.legs],
        static_durations_s=[max(1, int(leg.static_duration_s)) for leg in parsed.legs],
        polyline=parsed.polyline,
    )


class GoogleTrafficProvider:
    def __init__(self) -> None:
        self._provider = get_google_routes_provider()
        self.last_route_polyline: str | None = None

    @property
    def enabled(self) -> bool:
        return self._provider.enabled

    def compute_routes(
        self,
        waypoints_ordered: list[Any],
        departure_time_iso: str,
        routing_preference: str | None = None,
        *,
        include_polyline: bool = False,
    ) -> list[GoogleRouteLeg]:
        result = self._provider.compute_routes(
            waypoints_ordered=waypoints_ordered,
            departure_time_iso=departure_time_iso,
            routing_preference=routing_preference,
            include_polyline=include_polyline,
        )
        self.last_route_polyline = result.polyline
        return result.legs

    def get_segment_times(self, stops_ordered: list[Any], departure_time_iso: str) -> list[int]:
        legs = self.compute_routes(stops_ordered, departure_time_iso, include_polyline=True)
        return [max(1, int(leg.duration_s)) for leg in legs]

    def get_matrix(
        self,
        origins: list[Any],
        destinations: list[Any],
        departure_time_iso: str,
        routing_preference: str | None = None,
    ) -> list[list[GoogleMatrixElement | None]]:
        return self._provider.compute_route_matrix(
            origins=origins,
            destinations=destinations,
            departure_time_iso=departure_time_iso,
            routing_preference=routing_preference,
        )

    def get_matrix_times(
        self,
        origins: list[Any],
        destinations: list[Any],
        departure_time_iso: str,
    ) -> list[list[int]]:
        matrix = self.get_matrix(origins, destinations, departure_time_iso)
        return [
            [max(1, int(cell.duration_s)) if cell is not None else 0 for cell in row]
            for row in matrix
        ]


_PROVIDER: GoogleTrafficProvider | None = None


def get_google_traffic_provider() -> GoogleTrafficProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = GoogleTrafficProvider()
    return _PROVIDER

