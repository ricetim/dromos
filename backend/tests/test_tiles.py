"""Tile proxy must never persist CARTO's "API KEY REQUIRED" placeholder.

CARTO answers keyless requests with HTTP 200 and a fixed watermark image, so a
proxy that treats 200 as "cache forever" poisons the cache for every area
viewed after the change.
"""
from pathlib import Path

import httpx
import pytest

from app.routers import tiles

PLACEHOLDER = (Path(__file__).parent / "fixtures" / "carto_placeholder_light.png").read_bytes()
REAL_TILE = b"\x89PNG\r\n\x1a\n" + b"real-tile-bytes" * 300


@pytest.fixture
def tile_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tiles, "TILE_DIR", tmp_path)
    return tmp_path


def _upstream(monkeypatch, body):
    calls = []

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def get(self, url, headers=None, params=None):
            calls.append((url, params))
            return httpx.Response(200, content=body)

    monkeypatch.setattr(tiles.httpx, "AsyncClient", FakeClient)
    return calls


def test_placeholder_fixture_is_recognised():
    assert tiles._is_placeholder(PLACEHOLDER)
    assert not tiles._is_placeholder(REAL_TILE)


def test_fresh_placeholder_is_not_cached(client, tile_dir, monkeypatch):
    _upstream(monkeypatch, PLACEHOLDER)
    resp = client.get("/api/tiles/light/13/1310/3166.png")
    assert resp.status_code == 502
    assert not (tile_dir / "light" / "13" / "1310" / "3166.png").exists()


def test_cached_placeholder_is_purged_and_refetched(client, tile_dir, monkeypatch):
    poisoned = tile_dir / "light" / "13" / "1310" / "3166.png"
    poisoned.parent.mkdir(parents=True)
    poisoned.write_bytes(PLACEHOLDER)
    calls = _upstream(monkeypatch, REAL_TILE)

    resp = client.get("/api/tiles/light/13/1310/3166.png")
    assert resp.status_code == 200
    assert resp.content == REAL_TILE
    assert calls, "a poisoned cache entry must trigger an upstream refetch"
    assert poisoned.read_bytes() == REAL_TILE


def test_good_cached_tile_served_without_network(client, tile_dir, monkeypatch):
    good = tile_dir / "light" / "13" / "1310" / "3166.png"
    good.parent.mkdir(parents=True)
    good.write_bytes(REAL_TILE)
    calls = _upstream(monkeypatch, PLACEHOLDER)

    resp = client.get("/api/tiles/light/13/1310/3166.png")
    assert resp.status_code == 200 and resp.content == REAL_TILE
    assert calls == []


def test_carto_key_sent_only_to_carto(client, tile_dir, monkeypatch):
    monkeypatch.setattr(tiles, "CARTO_API_KEY", "test-key")
    calls = _upstream(monkeypatch, REAL_TILE)

    client.get("/api/tiles/light/13/1310/3166.png")
    client.get("/api/tiles/dark/13/1310/3166.png")
    client.get("/api/tiles/standard/13/1310/3166.png")

    by_host = {url.split("/")[2]: params for url, params in calls}
    assert by_host["a.basemaps.cartocdn.com"] == {"key": "test-key"}
    assert by_host["a.tile.openstreetmap.org"] is None, "OSM must not receive the CARTO key"
