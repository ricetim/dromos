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

router = APIRouter(prefix="/api/tiles", tags=["tiles"])

TILE_DIR = Path(os.environ.get("DATA_DIR", "/data")) / "tiles"
TILE_DIR.mkdir(parents=True, exist_ok=True)

PROVIDERS = {
    "light":    "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
    "dark":     "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "standard": "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
}

HEADERS = {
    "User-Agent": "Domos/1.0 (personal running dashboard; tile caching proxy)",
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
        return Response(content=cache_path.read_bytes(), media_type="image/png")

    url = PROVIDERS[provider].format(z=z, x=x, y=y)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Upstream tile fetch failed")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Tile fetch error: {exc}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(resp.content)

    return Response(content=resp.content, media_type="image/png")
