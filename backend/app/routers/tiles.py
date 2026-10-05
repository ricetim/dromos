"""
Map tile caching proxy.

Tiles are fetched from upstream providers on first request and cached
to disk forever. All subsequent loads are served from local storage —
no external network call needed.

Supported providers:
  light   → CartoDB Positron
  dark    → CartoDB Dark Matter
  standard → OpenStreetMap
"""

import hashlib
import httpx
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.config import CARTO_API_KEY

router = APIRouter(prefix="/api/tiles", tags=["tiles"])

TILE_DIR = Path(os.environ.get("DATA_DIR", "/data")) / "tiles"
TILE_DIR.mkdir(parents=True, exist_ok=True)

PROVIDERS = {
    "light":    "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
    "dark":     "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "standard": "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
}

# CARTO began requiring an API key and, rather than erroring, answers every tile
# request with HTTP 200 and a fixed "API KEY REQUIRED" watermark image — one for
# the light styles, one for dark, identical at every z/x/y. Because a 200 used to
# mean "good tile, cache forever", those placeholders were written to disk for
# every area first viewed after the change (areas cached earlier kept working,
# which is why only unfamiliar locations broke). Recognise them by content hash.
_PLACEHOLDER_MD5 = {
    "502fc5f6793fad87dcf8ba3fa646c38f",  # CARTO light/voyager "API KEY REQUIRED"
    "df9307c738f2c6dbc0f8d31837019f98",  # CARTO dark_all "API KEY REQUIRED"
}
_PLACEHOLDER_SIZES = {2049, 2513}   # cheap pre-check before hashing a cached file


def _is_placeholder(data: bytes) -> bool:
    return hashlib.md5(data).hexdigest() in _PLACEHOLDER_MD5


# Providers that authenticate with CARTO's ``?key=`` query parameter. The key is
# added here, server-side, so it never appears in a URL the browser can see.
_CARTO_KEYED = {"light", "dark"}

HEADERS = {
    "User-Agent": "Dromos/1.0 (personal running dashboard; tile caching proxy)",
    "Accept": "image/png,image/*",
}


@router.get("/{provider}/{z}/{x}/{y}.png")
async def get_tile(provider: str, z: int, x: int, y: int):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    if not (0 <= z <= 19):
        raise HTTPException(status_code=400, detail="Invalid zoom level")

    cache_path = TILE_DIR / provider / str(z) / str(x) / f"{y}.png"
    if cache_path.exists():
        # Self-heal: a placeholder cached before this guard existed is dropped
        # and refetched instead of being served forever. The size check keeps
        # the common path to a stat() — real tiles are almost never these sizes.
        if cache_path.stat().st_size in _PLACEHOLDER_SIZES:
            data = cache_path.read_bytes()
            if _is_placeholder(data):
                cache_path.unlink(missing_ok=True)
            else:
                return Response(content=data, media_type="image/png")
        else:
            return Response(content=cache_path.read_bytes(), media_type="image/png")

    url = PROVIDERS[provider].format(z=z, x=x, y=y)
    params = {"key": CARTO_API_KEY} if provider in _CARTO_KEYED and CARTO_API_KEY else None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=HEADERS, params=params)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Upstream tile fetch failed")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Tile fetch error: {exc}")
    if _is_placeholder(resp.content):
        # Never cache it; a failed tile renders blank and is retried next view.
        raise HTTPException(status_code=502, detail=f"Upstream '{provider}' requires an API key")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(resp.content)

    return Response(content=resp.content, media_type="image/png")
