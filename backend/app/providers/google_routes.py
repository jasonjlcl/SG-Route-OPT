from __future__ import annotations

import json
import logging
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.cache import get_cache
from app.utils.settings import get_settings


LOGGER = logging.getLogger(__name__)

GOOGLE_COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GOOGLE_COMPUTE_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
MAX_INTERMEDIATES_PER_REQUEST = 25
DEFAULT_BUCKET_MINUTES = 10
SG_TZ = timezone(timedelta(hours=8))


@dataclass
class GoogleRouteLeg:
    distance_m: float
    duration_s: int
    static_duration_s: int


@dataclass
class GoogleRouteResult:
    legs: list[GoogleRouteLeg]
    polyline: str | None = None


@dataclass
class GoogleMatrixElement:
    origin_index: int
    destination_index: int
    distance_m: float
    duration_s: int
    static_duration_s: int


class GoogleRoutesError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "GOOGLE_ROUTES_ERROR",
        status_code: int | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}


class _TokenBucketLimiter:
    def __init__(self, *, qps: float) -> None:
        safe_qps = float(max(0.5, qps))
        self._rate = safe_qps
        self._capacity = max(1.0, safe_qps)
        self._tokens = self._capacity
        self._updated_at = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self._updated_at)
                self._updated_at = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                needed_s = (1.0 - self._tokens) / self._rate
            time.sleep(min(0.25, max(0.01, needed_s)))


def parse_google_duration_seconds(value: str | int | float | None) -> int:
    if value is None:
        raise ValueError("Duration value is missing")
    if isinstance(value, (int, float)):
        return max(0, int(round(float(value))))

    text = str(value).strip()
    if text.endswith("s"):
        text = text[:-1]
    return max(0, int(round(float(text))))


class GoogleRoutesProvider:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cache = get_cache()
        timeout = max(1, int(self.settings.google_timeout_seconds))
        self.http = httpx.Client(timeout=timeout)
        self._limiter = _TokenBucketLimiter(qps=float(self.settings.google_rate_limit_qps))
        self._cache_ttl_seconds = max(30, int(self.settings.google_cache_ttl_seconds))
        self.last_route_polyline: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.feature_google_traffic and self.settings.resolved_google_routes_api_key)

    @staticmethod
    def _extract_lat_lon(node: Any) -> tuple[float, float]:
        lat: Any = None
        lon: Any = None
        if isinstance(node, dict):
            lat = node.get("lat") if "lat" in node else node.get("latitude")
            lon = node.get("lon") if "lon" in node else node.get("longitude")
        else:
            lat = getattr(node, "lat", None)
            lon = getattr(node, "lon", None)
        if lat is None or lon is None:
            raise GoogleRoutesError("Invalid waypoint coordinates", code="GOOGLE_INPUT_INVALID")
        return float(lat), float(lon)

    @staticmethod
    def _normalize_departure(value: str) -> datetime:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=SG_TZ)
        return dt

    @staticmethod
    def _bucket_for_departure(dt: datetime) -> tuple[int, str]:
        minute = (dt.minute // DEFAULT_BUCKET_MINUTES) * DEFAULT_BUCKET_MINUTES
        bucket = dt.replace(minute=minute, second=0, microsecond=0)
        return int(bucket.weekday()), bucket.strftime("%H:%M")

    @staticmethod
    def _round(v: float) -> float:
        return round(v, 5)

    @staticmethod
    def _routing_preference(value: str | None) -> str:
        if value:
            return str(value).upper()
        settings = get_settings()
        return settings.resolved_google_routing_preference

    def _leg_cache_key(
        self,
        *,
        origin: tuple[float, float],
        dest: tuple[float, float],
        departure: datetime,
        routing_preference: str,
    ) -> str:
        dow, time_bucket = self._bucket_for_departure(departure)
        return (
            "google_routes_leg:"
            f"{self._round(origin[0])}:{self._round(origin[1])}:"
            f"{self._round(dest[0])}:{self._round(dest[1])}:"
            f"{dow}:{time_bucket}:{routing_preference}"
        )

    def _headers(self, *, field_mask: str) -> dict[str, str]:
        api_key = self.settings.resolved_google_routes_api_key
        if not api_key:
            raise GoogleRoutesError("Google Routes API key is not configured", code="GOOGLE_KEY_MISSING")
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": field_mask,
        }

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(min(3.0, (2**attempt) * 0.2 + 0.05))

    @staticmethod
    def _request_error_details(exc: Exception) -> dict[str, Any]:
        details: dict[str, Any] = {
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
        request = getattr(exc, "request", None)
        if request is not None:
            details["method"] = str(getattr(request, "method", "") or "")
            details["url"] = str(getattr(request, "url", "") or "")
        cause = exc.__cause__
        if cause is not None:
            details["cause_type"] = cause.__class__.__name__
            details["cause"] = str(cause)
            errno = getattr(cause, "errno", None)
            if isinstance(errno, int):
                details["cause_errno"] = int(errno)
        return details

    @staticmethod
    def _dns_probe(host: str) -> dict[str, Any]:
        details: dict[str, Any] = {"host": host}
        try:
            entries = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            ips: list[str] = []
            for entry in entries:
                sockaddr = entry[4]
                if not isinstance(sockaddr, tuple) or not sockaddr:
                    continue
                ip = str(sockaddr[0])
                if ip and ip not in ips:
                    ips.append(ip)
                if len(ips) >= 3:
                    break
            details["resolved_count"] = len(ips)
            details["resolved_ips"] = ips
        except OSError as exc:
            details["dns_error_type"] = exc.__class__.__name__
            details["dns_error"] = str(exc)
            if isinstance(getattr(exc, "errno", None), int):
                details["dns_errno"] = int(exc.errno)
        return details

    def _post(self, *, url: str, payload: dict[str, Any], field_mask: str, max_attempts: int = 3) -> httpx.Response:
        last_error: GoogleRoutesError | None = None
        for attempt in range(max_attempts):
            self._limiter.acquire()
            try:
                response = self.http.post(url, json=payload, headers=self._headers(field_mask=field_mask))
            except httpx.TimeoutException as exc:
                error_details = self._request_error_details(exc)
                error_details["attempt"] = attempt + 1
                error_details["max_attempts"] = max_attempts
                last_error = GoogleRoutesError(
                    "Google Routes request timed out",
                    code="GOOGLE_ROUTES_TIMEOUT",
                    retryable=True,
                    details=error_details,
                )
                if attempt == max_attempts - 1:
                    raise last_error from exc
                self._sleep_backoff(attempt)
                continue
            except httpx.RequestError as exc:
                error_details = self._request_error_details(exc)
                error_details["attempt"] = attempt + 1
                error_details["max_attempts"] = max_attempts
                if attempt == max_attempts - 1:
                    error_details["dns_probe"] = self._dns_probe("routes.googleapis.com")
                last_error = GoogleRoutesError(
                    "Google Routes request failed",
                    code="GOOGLE_ROUTES_REQUEST_ERROR",
                    retryable=True,
                    details=error_details,
                )
                if attempt == max_attempts - 1:
                    LOGGER.warning(
                        "Google Routes request error after retries (details=%s)",
                        error_details,
                    )
                if attempt == max_attempts - 1:
                    raise last_error from exc
                self._sleep_backoff(attempt)
                continue

            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = GoogleRoutesError(
                    "Google Routes unavailable",
                    code="GOOGLE_ROUTES_UNAVAILABLE",
                    status_code=response.status_code,
                    retryable=True,
                    details={"status_code": response.status_code},
                )
                if attempt == max_attempts - 1:
                    raise last_error
                self._sleep_backoff(attempt)
                continue

            if response.status_code >= 400:
                raise GoogleRoutesError(
                    "Google Routes request rejected",
                    code="GOOGLE_ROUTES_REJECTED",
                    status_code=response.status_code,
                    details={"status_code": response.status_code, "body": response.text[:300]},
                )

            return response

        if last_error:
            raise last_error
        raise GoogleRoutesError("Google Routes request failed", code="GOOGLE_ROUTES_ERROR")

    @staticmethod
    def _waypoint(lat: float, lon: float) -> dict[str, Any]:
        return {
            "location": {
                "latLng": {
                    "latitude": float(lat),
                    "longitude": float(lon),
                }
            }
        }

    @staticmethod
    def _split_points(points: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
        max_points = MAX_INTERMEDIATES_PER_REQUEST + 2
        if len(points) <= max_points:
            return [points]

        chunks: list[list[tuple[float, float]]] = []
        start = 0
        while start < len(points) - 1:
            end = min(len(points), start + max_points)
            chunk = points[start:end]
            if len(chunk) < 2:
                break
            chunks.append(chunk)
            if end == len(points):
                break
            start = end - 1
        return chunks

    def _get_cached_leg(
        self,
        *,
        origin: tuple[float, float],
        dest: tuple[float, float],
        departure: datetime,
        routing_preference: str,
    ) -> GoogleRouteLeg | None:
        key = self._leg_cache_key(origin=origin, dest=dest, departure=departure, routing_preference=routing_preference)
        hit = self.cache.get(key)
        if not isinstance(hit, dict):
            return None
        try:
            return GoogleRouteLeg(
                distance_m=float(hit.get("distance_m") or 0.0),
                duration_s=max(1, int(hit["duration_s"])),
                static_duration_s=max(1, int(hit.get("static_duration_s") or hit["duration_s"])),
            )
        except Exception:
            return None

    def _set_cached_leg(
        self,
        *,
        origin: tuple[float, float],
        dest: tuple[float, float],
        departure: datetime,
        routing_preference: str,
        leg: GoogleRouteLeg,
    ) -> None:
        key = self._leg_cache_key(origin=origin, dest=dest, departure=departure, routing_preference=routing_preference)
        self.cache.set(
            key,
            {
                "duration_s": max(1, int(leg.duration_s)),
                "static_duration_s": max(1, int(leg.static_duration_s)),
                "distance_m": float(leg.distance_m),
                "routing_preference": routing_preference,
                "cached_at": datetime.utcnow().isoformat(),
            },
            ttl_seconds=self._cache_ttl_seconds,
        )

    @staticmethod
    def parse_compute_routes_payload(payload: dict[str, Any], *, expected_legs: int | None = None) -> GoogleRouteResult:
        routes = payload.get("routes")
        if not isinstance(routes, list) or not routes:
            raise GoogleRoutesError("Google Routes response has no routes", code="GOOGLE_ROUTES_EMPTY")

        route = routes[0]
        if not isinstance(route, dict):
            raise GoogleRoutesError("Google Routes route format invalid", code="GOOGLE_ROUTES_INVALID")

        legs_obj = route.get("legs")
        if not isinstance(legs_obj, list) or not legs_obj:
            raise GoogleRoutesError("Google Routes response has no legs", code="GOOGLE_LEGS_MISSING")

        if expected_legs is not None and len(legs_obj) != expected_legs:
            raise GoogleRoutesError(
                "Google Routes leg count mismatch",
                code="GOOGLE_LEG_COUNT_MISMATCH",
                details={"expected": expected_legs, "actual": len(legs_obj)},
            )

        legs: list[GoogleRouteLeg] = []
        for leg in legs_obj:
            if not isinstance(leg, dict):
                raise GoogleRoutesError("Google Routes leg format invalid", code="GOOGLE_LEG_INVALID")
            duration_s = parse_google_duration_seconds(leg.get("duration"))
            static_duration_raw = leg.get("staticDuration")
            static_duration_s = parse_google_duration_seconds(static_duration_raw) if static_duration_raw is not None else duration_s
            legs.append(
                GoogleRouteLeg(
                    distance_m=float(leg.get("distanceMeters") or 0.0),
                    duration_s=max(1, duration_s),
                    static_duration_s=max(1, static_duration_s),
                )
            )

        polyline = None
        polyline_obj = route.get("polyline")
        if isinstance(polyline_obj, dict):
            encoded = polyline_obj.get("encodedPolyline")
            if encoded:
                polyline = str(encoded)

        return GoogleRouteResult(legs=legs, polyline=polyline)

    @staticmethod
    def _parse_matrix_elements(raw_text: str, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            if isinstance(payload.get("matrix"), list):
                return [item for item in payload["matrix"] if isinstance(item, dict)]
            if isinstance(payload.get("elements"), list):
                return [item for item in payload["elements"] if isinstance(item, dict)]

        elements: list[dict[str, Any]] = []
        for line in raw_text.splitlines():
            line = line.strip().rstrip(",")
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                elements.append(parsed)
        return elements

    def compute_routes(
        self,
        waypoints_ordered: list[Any],
        departure_time_iso: str,
        routing_preference: str | None = None,
        *,
        include_polyline: bool = False,
    ) -> GoogleRouteResult:
        if len(waypoints_ordered) < 2:
            return GoogleRouteResult(legs=[], polyline=None)
        if not self.enabled:
            raise GoogleRoutesError("Google traffic feature disabled", code="GOOGLE_ROUTES_DISABLED")

        points = [self._extract_lat_lon(node) for node in waypoints_ordered]
        departure = self._normalize_departure(departure_time_iso)
        preference = self._routing_preference(routing_preference)

        cached_legs: list[GoogleRouteLeg] = []
        cache_complete = True
        for origin, dest in zip(points[:-1], points[1:]):
            cached = self._get_cached_leg(origin=origin, dest=dest, departure=departure, routing_preference=preference)
            if cached is None:
                cache_complete = False
                break
            cached_legs.append(cached)
        if cache_complete:
            return GoogleRouteResult(legs=cached_legs, polyline=self.last_route_polyline)

        all_legs: list[GoogleRouteLeg] = []
        polyline: str | None = None
        for chunk in self._split_points(points):
            payload = {
                "origin": self._waypoint(chunk[0][0], chunk[0][1]),
                "destination": self._waypoint(chunk[-1][0], chunk[-1][1]),
                "travelMode": "DRIVE",
                "routingPreference": preference,
                "departureTime": departure.isoformat(),
                "computeAlternativeRoutes": False,
                "languageCode": "en-US",
                "units": "METRIC",
            }
            if len(chunk) > 2:
                payload["intermediates"] = [self._waypoint(lat, lon) for lat, lon in chunk[1:-1]]

            field_mask = "routes.legs.duration,routes.legs.staticDuration,routes.legs.distanceMeters"
            if include_polyline:
                field_mask = f"{field_mask},routes.polyline.encodedPolyline"
            response = self._post(url=GOOGLE_COMPUTE_ROUTES_URL, payload=payload, field_mask=field_mask)
            parsed = self.parse_compute_routes_payload(response.json(), expected_legs=len(chunk) - 1)
            all_legs.extend(parsed.legs)
            if parsed.polyline:
                polyline = parsed.polyline

        expected = len(points) - 1
        if len(all_legs) != expected:
            raise GoogleRoutesError(
                "Google Routes leg count mismatch",
                code="GOOGLE_LEG_COUNT_MISMATCH",
                details={"expected": expected, "actual": len(all_legs)},
            )

        for idx, (origin, dest) in enumerate(zip(points[:-1], points[1:])):
            self._set_cached_leg(
                origin=origin,
                dest=dest,
                departure=departure,
                routing_preference=preference,
                leg=all_legs[idx],
            )

        self.last_route_polyline = polyline
        return GoogleRouteResult(legs=all_legs, polyline=polyline)

    def compute_route_matrix(
        self,
        origins: list[Any],
        destinations: list[Any],
        departure_time_iso: str,
        routing_preference: str | None = None,
    ) -> list[list[GoogleMatrixElement | None]]:
        if not origins or not destinations:
            return []
        if not self.enabled:
            raise GoogleRoutesError("Google traffic feature disabled", code="GOOGLE_ROUTES_DISABLED")

        departure = self._normalize_departure(departure_time_iso)
        preference = self._routing_preference(routing_preference)
        if preference == "TRAFFIC_AWARE_OPTIMAL":
            # Keep matrix calls cost-safe; optimal preference is reserved for final per-route refinement.
            preference = "TRAFFIC_AWARE"

        max_elements = int(self.settings.resolved_google_matrix_max_elements)
        total_elements = len(origins) * len(destinations)
        if total_elements > max_elements:
            raise GoogleRoutesError(
                "Google matrix guardrail exceeded",
                code="GOOGLE_MATRIX_LIMIT_EXCEEDED",
                details={"elements": total_elements, "max": max_elements},
            )

        origin_points = [self._extract_lat_lon(item) for item in origins]
        destination_points = [self._extract_lat_lon(item) for item in destinations]

        matrix: list[list[GoogleMatrixElement | None]] = [
            [None for _ in destinations] for _ in origins
        ]
        cache_complete = True
        for i, origin in enumerate(origin_points):
            for j, destination in enumerate(destination_points):
                if len(origins) == len(destinations) and i == j:
                    matrix[i][j] = GoogleMatrixElement(
                        origin_index=i,
                        destination_index=j,
                        distance_m=0.0,
                        duration_s=1,
                        static_duration_s=1,
                    )
                    continue
                cached = self._get_cached_leg(
                    origin=origin,
                    dest=destination,
                    departure=departure,
                    routing_preference=preference,
                )
                if cached is None:
                    cache_complete = False
                    continue
                matrix[i][j] = GoogleMatrixElement(
                    origin_index=i,
                    destination_index=j,
                    distance_m=float(cached.distance_m),
                    duration_s=max(1, int(cached.duration_s)),
                    static_duration_s=max(1, int(cached.static_duration_s)),
                )
        if cache_complete:
            return matrix

        payload = {
            "origins": [{"waypoint": self._waypoint(lat, lon)} for lat, lon in origin_points],
            "destinations": [{"waypoint": self._waypoint(lat, lon)} for lat, lon in destination_points],
            "travelMode": "DRIVE",
            "routingPreference": preference,
            "departureTime": departure.isoformat(),
        }
        field_mask = "originIndex,destinationIndex,duration,staticDuration,distanceMeters,condition,status"
        response = self._post(url=GOOGLE_COMPUTE_MATRIX_URL, payload=payload, field_mask=field_mask)

        raw_text = response.text.strip()
        payload_json: Any = None
        try:
            payload_json = response.json()
        except Exception:
            payload_json = None
        elements = self._parse_matrix_elements(raw_text, payload_json)

        missing = 0
        for element in elements:
            try:
                i = int(element.get("originIndex", -1))
                j = int(element.get("destinationIndex", -1))
            except Exception:
                continue
            if i < 0 or j < 0 or i >= len(origins) or j >= len(destinations):
                continue

            condition = str(element.get("condition") or "")
            if condition and condition != "ROUTE_EXISTS":
                continue
            duration_raw = element.get("duration")
            if duration_raw is None:
                continue

            duration_s = max(1, parse_google_duration_seconds(duration_raw))
            static_raw = element.get("staticDuration")
            static_duration_s = max(1, parse_google_duration_seconds(static_raw)) if static_raw is not None else duration_s
            distance_m = float(element.get("distanceMeters") or 0.0)

            matrix[i][j] = GoogleMatrixElement(
                origin_index=i,
                destination_index=j,
                distance_m=distance_m,
                duration_s=duration_s,
                static_duration_s=static_duration_s,
            )
            self._set_cached_leg(
                origin=origin_points[i],
                dest=destination_points[j],
                departure=departure,
                routing_preference=preference,
                leg=GoogleRouteLeg(distance_m=distance_m, duration_s=duration_s, static_duration_s=static_duration_s),
            )

        for i in range(len(origins)):
            for j in range(len(destinations)):
                if matrix[i][j] is None:
                    missing += 1

        if missing > 0:
            LOGGER.warning("Google matrix partial coverage; missing elements=%s", missing)

        return matrix


_PROVIDER: GoogleRoutesProvider | None = None


def get_google_routes_provider() -> GoogleRoutesProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = GoogleRoutesProvider()
    return _PROVIDER
