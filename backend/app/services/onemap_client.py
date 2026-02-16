from __future__ import annotations

import hashlib
import math
import random
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.cache import get_cache
from app.utils.settings import get_settings


class OneMapClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cache = get_cache()
        self.http = httpx.Client(timeout=20)

    @property
    def mock_mode(self) -> bool:
        return not self.settings.onemap_email or not self.settings.onemap_password

    def _token_cache_key(self) -> str:
        return "onemap:access_token"

    def _parse_expiry(self, payload: dict[str, Any]) -> int:
        now = int(time.time())
        expiry_raw = payload.get("expiry_timestamp") or payload.get("expiry")
        if isinstance(expiry_raw, (int, float)):
            expiry_ts = int(expiry_raw)
            if expiry_ts > now + 60:
                return expiry_ts
        if isinstance(expiry_raw, str):
            try:
                parsed = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
                return int(parsed.timestamp())
            except ValueError:
                pass
        return now + 3600

    def _fetch_token(self) -> dict[str, Any]:
        resp = self.http.post(
            self.settings.onemap_auth_url,
            json={
                "email": self.settings.onemap_email,
                "password": self.settings.onemap_password,
            },
        )
        resp.raise_for_status()
        payload = resp.json()

        token = payload.get("access_token") or payload.get("token")
        if not token:
            raise RuntimeError("OneMap auth response missing token")

        expiry_ts = self._parse_expiry(payload)
        ttl = max(60, expiry_ts - int(time.time()) - 30)
        token_data = {"token": token, "expiry_ts": expiry_ts}
        self.cache.set(self._token_cache_key(), token_data, ttl_seconds=ttl)
        return token_data

    def get_access_token(self, force_refresh: bool = False) -> str | None:
        if self.mock_mode:
            return None

        if force_refresh:
            self.cache.delete(self._token_cache_key())

        cached = self.cache.get(self._token_cache_key())
        if cached and int(cached.get("expiry_ts", 0)) > int(time.time()) + 30:
            return cached["token"]

        token_data = self._fetch_token()
        return token_data["token"]

    def _request_with_retries(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        max_attempts: int = 4,
    ) -> dict[str, Any]:
        refreshed = False

        for attempt in range(max_attempts):
            headers: dict[str, str] = {}
            token = self.get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

            try:
                resp = self.http.request(method, url, params=params, headers=headers)
            except httpx.RequestError:
                if attempt == max_attempts - 1:
                    raise
                self._sleep_backoff(attempt)
                continue

            if resp.status_code == 401 and not self.mock_mode and not refreshed:
                self.get_access_token(force_refresh=True)
                refreshed = True
                continue

            if resp.status_code in {429, 500, 502, 503, 504}:
                if attempt == max_attempts - 1:
                    resp.raise_for_status()
                self._sleep_backoff(attempt)
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError("OneMap request failed after retries")

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        sleep_time = min(4.0, (2**attempt) * 0.25 + random.random() * 0.15)
        time.sleep(sleep_time)

    def search(self, query: str) -> dict[str, Any]:
        params = {
            "searchVal": query,
            "returnGeom": "Y",
            "getAddrDetails": "Y",
            "pageNum": 1,
        }
        try:
            return self._request_with_retries(
                "GET",
                self.settings.onemap_search_url,
                params=params,
            )
        except Exception:
            # Search endpoint is generally public, but if unavailable, keep local dev usable.
            lat, lon = self._mock_lat_lon(query)
            return {
                "found": 1,
                "results": [
                    {
                        "ADDRESS": query,
                        "POSTAL": self._extract_postal(query),
                        "LATITUDE": str(lat),
                        "LONGITUDE": str(lon),
                        "MOCK": "true",
                    }
                ],
            }

    def route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        route_type: str = "drive",
    ) -> dict[str, float]:
        if self.mock_mode:
            distance = self._haversine_m(origin_lat, origin_lon, dest_lat, dest_lon)
            duration = max(30.0, distance / 9.0)
            return {"distance_m": distance, "duration_s": duration}

        data = self._request_with_retries(
            "GET",
            self.settings.onemap_routing_url,
            params={
                "start": f"{origin_lat},{origin_lon}",
                "end": f"{dest_lat},{dest_lon}",
                "routeType": route_type,
            },
        )

        summary = data.get("route_summary", {})
        distance = float(summary.get("total_distance") or 0)
        duration = float(summary.get("total_time") or 0)
        if distance <= 0 or duration <= 0:
            raise RuntimeError("Invalid OneMap routing response")
        return {"distance_m": distance, "duration_s": duration}

    @staticmethod
    def _extract_postal(query: str) -> str:
        digits = "".join(ch for ch in query if ch.isdigit())
        if len(digits) >= 6:
            return digits[:6]
        return "000000"

    @staticmethod
    def _mock_lat_lon(query: str) -> tuple[float, float]:
        sg_lat, sg_lon = 1.3521, 103.8198
        h = hashlib.sha256(query.encode("utf-8")).hexdigest()
        lat_offset = (int(h[:8], 16) % 2000 - 1000) / 100000
        lon_offset = (int(h[8:16], 16) % 2000 - 1000) / 100000
        return sg_lat + lat_offset, sg_lon + lon_offset

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6371000.0
        p = math.pi / 180
        dlat = (lat2 - lat1) * p
        dlon = (lon2 - lon1) * p
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
        )
        return 2 * radius * math.asin(math.sqrt(a))


_client: OneMapClient | None = None


def get_onemap_client() -> OneMapClient:
    global _client
    if _client is None:
        _client = OneMapClient()
    return _client
