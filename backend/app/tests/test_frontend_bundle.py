from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main as main_module


def _write_frontend_dist(tmp_path: Path) -> tuple[Path, Path]:
    dist = tmp_path / "frontend_dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    index = dist / "index.html"
    asset = assets / "main.js"
    index.write_text("<html>bundle</html>", encoding="utf-8")
    asset.write_text("console.log('bundle');", encoding="utf-8")
    return dist, asset


def test_frontend_response_serves_index_for_spa_routes(tmp_path, monkeypatch):
    dist, _ = _write_frontend_dist(tmp_path)
    monkeypatch.setattr(main_module, "FRONTEND_DIR_CANDIDATES", (dist,))

    response = main_module._frontend_response("results")

    assert Path(response.path).resolve() == (dist / "index.html").resolve()


def test_frontend_response_serves_static_asset_when_present(tmp_path, monkeypatch):
    dist, asset = _write_frontend_dist(tmp_path)
    monkeypatch.setattr(main_module, "FRONTEND_DIR_CANDIDATES", (dist,))

    response = main_module._frontend_response("assets/main.js")

    assert Path(response.path).resolve() == asset.resolve()


def test_frontend_response_rejects_reserved_api_paths(tmp_path, monkeypatch):
    dist, _ = _write_frontend_dist(tmp_path)
    monkeypatch.setattr(main_module, "FRONTEND_DIR_CANDIDATES", (dist,))

    with pytest.raises(HTTPException) as exc:
        main_module._frontend_response("api/v1/health")

    assert exc.value.status_code == 404
