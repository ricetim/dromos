import json

import brotli
import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.middleware.gzip import GZipMiddleware

from app.main import PrecompressedStaticFiles
from app.services import precompress
from app.services.builder import _write_json


# ── helper-level ─────────────────────────────────────────────────────────────

def test_write_br_roundtrips(tmp_path):
    p = tmp_path / "data.json"
    payload = json.dumps({"x": list(range(500))}).encode()
    p.write_bytes(payload)
    precompress.write_br(p, payload)
    br = p.with_name(p.name + ".br")
    assert br.is_file()
    assert brotli.decompress(br.read_bytes()) == payload
    # no leftover temp file
    assert not br.with_name(br.name + ".tmp").exists()


def test_precompress_dir_skips_small_and_binary(tmp_path):
    big = tmp_path / "bundle.js"
    big.write_text("console.log('x');" * 200)          # > 1 KiB, compressible
    small = tmp_path / "tiny.json"
    small.write_text("{}")                               # < 1 KiB → skipped
    img = tmp_path / "logo.png"
    img.write_bytes(b"\x89PNG" + b"\x00" * 2000)         # binary ext → skipped

    n = precompress.precompress_dir(tmp_path)

    assert n == 1
    assert (tmp_path / "bundle.js.br").is_file()
    assert not (tmp_path / "tiny.json.br").exists()
    assert not (tmp_path / "logo.png.br").exists()


def test_write_json_emits_decodable_br_sibling(tmp_path):
    target = tmp_path / "activities.json"
    data = {"a": 1, "items": list(range(300))}
    _write_json(target, data)
    br = tmp_path / "activities.json.br"
    assert br.is_file()
    assert json.loads(brotli.decompress(br.read_bytes())) == data


# ── HTTP-level (PrecompressedStaticFiles behind GZipMiddleware) ───────────────

@pytest.fixture
def br_client(tmp_path):
    payload = json.dumps({"x": list(range(500))}).encode()
    (tmp_path / "data.json").write_bytes(payload)
    precompress.write_br(tmp_path / "data.json", payload)

    app = Starlette()
    app.add_middleware(GZipMiddleware, minimum_size=1)
    app.mount("/static", PrecompressedStaticFiles(directory=str(tmp_path)))
    return TestClient(app), payload


def test_serves_brotli_when_accepted(br_client):
    client, payload = br_client
    r = client.get("/static/data.json", headers={"Accept-Encoding": "br"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "br"
    assert "Accept-Encoding" in r.headers.get("vary", "")
    assert r.content == payload            # httpx auto-decodes br
    assert r.headers["content-type"].startswith("application/json")


def test_falls_back_to_gzip_without_br(br_client):
    client, _ = br_client
    r = client.get("/static/data.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"


def test_no_double_encoding_when_both_accepted(br_client):
    # Accept-Encoding advertises gzip too, so GZipMiddleware engages — but our
    # response already carries Content-Encoding: br, so it must pass through.
    client, _ = br_client
    r = client.get("/static/data.json", headers={"Accept-Encoding": "br, gzip"})
    assert r.headers["content-encoding"] == "br"


def test_range_request_bypasses_brotli(br_client):
    # A Range request must never be answered with a Brotli stream: a byte range
    # of compressed data isn't independently decodable. (Starlette's FileResponse
    # ignores Range and returns the full body, but the key guarantee is that the
    # response is not Content-Encoding: br.)
    client, payload = br_client
    r = client.get(
        "/static/data.json",
        headers={"Accept-Encoding": "br", "Range": "bytes=0-9"},
    )
    assert r.headers.get("content-encoding") != "br"
    assert r.content == payload
