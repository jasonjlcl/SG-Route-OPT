from sqlalchemy import func, select

from app.models import OdCache
from app.services.routing import RoutingService
from app.utils.db import SessionLocal


def test_routing_fallback_not_persisted_to_od_cache(monkeypatch):
    service = RoutingService()

    monkeypatch.setattr(
        service.client,
        "route",
        lambda *args, **kwargs: {
            "distance_m": 1200.0,
            "duration_s": 240.0,
            "source": "heuristic_fallback",
            "is_fallback": True,
        },
    )

    db = SessionLocal()
    try:
        route = service.get_base_route(
            db,
            origin_lat=1.3001,
            origin_lon=103.8001,
            dest_lat=1.3101,
            dest_lon=103.8101,
            depart_bucket="08:00",
            day_of_week=2,
        )
        assert route.od_cache_id == -1
        count = db.execute(select(func.count(OdCache.id))).scalar_one()
        assert int(count) == 0
    finally:
        db.close()


def test_routing_onemap_result_persisted_to_od_cache(monkeypatch):
    service = RoutingService()

    monkeypatch.setattr(
        service.client,
        "route",
        lambda *args, **kwargs: {
            "distance_m": 1500.0,
            "duration_s": 300.0,
            "source": "onemap",
            "is_fallback": False,
        },
    )

    db = SessionLocal()
    try:
        route = service.get_base_route(
            db,
            origin_lat=1.3002,
            origin_lon=103.8002,
            dest_lat=1.3102,
            dest_lon=103.8102,
            depart_bucket="08:05",
            day_of_week=2,
        )
        assert route.od_cache_id > 0
        count = db.execute(select(func.count(OdCache.id))).scalar_one()
        assert int(count) == 1
    finally:
        db.close()
