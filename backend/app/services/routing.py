from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OdCache
from app.services.cache import get_cache
from app.services.onemap_client import get_onemap_client


@dataclass
class BaseRoute:
    od_cache_id: int
    distance_m: float
    duration_s: float


class RoutingService:
    def __init__(self) -> None:
        self.cache = get_cache()
        self.client = get_onemap_client()

    @staticmethod
    def _round(v: float) -> float:
        return round(v, 5)

    def _key(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        depart_bucket: str,
        day_of_week: int,
    ) -> str:
        return (
            "route:"
            f"{self._round(origin_lat)}:{self._round(origin_lon)}:"
            f"{self._round(dest_lat)}:{self._round(dest_lon)}:{depart_bucket}:{day_of_week}"
        )

    def get_base_route(
        self,
        db: Session,
        *,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        depart_bucket: str,
        day_of_week: int,
    ) -> BaseRoute:
        if origin_lat == dest_lat and origin_lon == dest_lon:
            temp = OdCache(
                id=-1,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                dest_lat=dest_lat,
                dest_lon=dest_lon,
                depart_bucket=depart_bucket,
                day_of_week=day_of_week,
                base_distance_m=0,
                base_duration_s=0,
            )
            return BaseRoute(od_cache_id=temp.id, distance_m=0, duration_s=0)

        key = self._key(origin_lat, origin_lon, dest_lat, dest_lon, depart_bucket, day_of_week)
        redis_hit = self.cache.get(key)
        if redis_hit:
            return BaseRoute(
                od_cache_id=int(redis_hit["od_cache_id"]),
                distance_m=float(redis_hit["distance_m"]),
                duration_s=float(redis_hit["duration_s"]),
            )

        stmt = select(OdCache).where(
            OdCache.origin_lat == self._round(origin_lat),
            OdCache.origin_lon == self._round(origin_lon),
            OdCache.dest_lat == self._round(dest_lat),
            OdCache.dest_lon == self._round(dest_lon),
            OdCache.depart_bucket == depart_bucket,
            OdCache.day_of_week == day_of_week,
        )
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            self.cache.set(
                key,
                {
                    "od_cache_id": existing.id,
                    "distance_m": existing.base_distance_m,
                    "duration_s": existing.base_duration_s,
                },
                ttl_seconds=24 * 3600,
            )
            return BaseRoute(od_cache_id=existing.id, distance_m=existing.base_distance_m, duration_s=existing.base_duration_s)

        route = self.client.route(origin_lat, origin_lon, dest_lat, dest_lon)
        record = OdCache(
            origin_lat=self._round(origin_lat),
            origin_lon=self._round(origin_lon),
            dest_lat=self._round(dest_lat),
            dest_lon=self._round(dest_lon),
            depart_bucket=depart_bucket,
            day_of_week=day_of_week,
            base_distance_m=float(route["distance_m"]),
            base_duration_s=float(route["duration_s"]),
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        self.cache.set(
            key,
            {
                "od_cache_id": record.id,
                "distance_m": record.base_distance_m,
                "duration_s": record.base_duration_s,
            },
            ttl_seconds=24 * 3600,
        )

        return BaseRoute(od_cache_id=record.id, distance_m=record.base_distance_m, duration_s=record.base_duration_s)


_service: RoutingService | None = None


def get_routing_service() -> RoutingService:
    global _service
    if _service is None:
        _service = RoutingService()
    return _service
