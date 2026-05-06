import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles
from app.database import create_db_and_tables
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()


def _startup_rebuild():
    """
    On first startup (no activities.json), run a full static rebuild.
    On subsequent starts, warm the in-process TTL caches only.
    """
    from app.database import Session, engine
    from app.services.builder import STATIC_DIR, rebuild_all
    from app.routers.activities import warm_cache as warm_activities
    from app.routers.stats import warm_cache as warm_stats

    with Session(engine) as session:
        if not (STATIC_DIR / "activities.json").exists():
            print("[startup] Static files missing — running full rebuild...")
            rebuild_all(session)
            print("[startup] Rebuild complete.")
        else:
            warm_activities(session)
            warm_stats(session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    from app.routers.sync import _sync_strava_activities, _sync_coros
    from app.config import STRAVA_REFRESH_TOKEN, COROS_EMAIL
    if STRAVA_REFRESH_TOKEN:
        scheduler.add_job(_sync_strava_activities, "interval", hours=6)
    if COROS_EMAIL:
        scheduler.add_job(_sync_coros, "interval", minutes=30)
    scheduler.start()
    threading.Thread(target=_startup_rebuild, daemon=True).start()
    yield
    scheduler.shutdown()


app = FastAPI(title="RunScribe", lifespan=lifespan)

# GZip first (outermost) so all responses — including CORS preflight — are compressed
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.routers import activities, stats, sync, shoes, goals, plans, profile, tiles
app.include_router(activities.router)
app.include_router(stats.router)
app.include_router(sync.router)
app.include_router(shoes.router)
app.include_router(goals.router)
app.include_router(plans.router)
app.include_router(profile.router)
app.include_router(tiles.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Static file serving ────────────────────────────────────────────────────


class SPAStaticFiles(StaticFiles):
    """Serve React SPA: try the requested file, fall back to index.html for
    client-side routes (e.g. /activities/123 → index.html).

    Must catch starlette.exceptions.HTTPException (base class), not
    fastapi.HTTPException (subclass) — StaticFiles raises the base class.
    """
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        # Vite outputs content-hashed filenames — safe to cache forever
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif not path.startswith("/api/"):
        # HTML and data files should always be re-validated
        response.headers["Cache-Control"] = "no-cache"
    return response


# Ensure data/static dir exists before mounting (created by builder on first run)
_static_dir = Path(os.environ.get("DATA_DIR", "/data")) / "static"
_static_dir.mkdir(parents=True, exist_ok=True)

# Mount order matters: specific prefixes before the catch-all "/"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="data-static")
_spa_dir = os.environ.get("SPA_DIR", "/app/frontend")
if Path(_spa_dir).is_dir():
    app.mount("/", SPAStaticFiles(directory=_spa_dir, html=True), name="spa")
