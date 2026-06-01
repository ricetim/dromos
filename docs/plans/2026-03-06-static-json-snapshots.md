# Static JSON Snapshots Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace live API reads with pre-built static JSON files so all read requests are served by nginx from disk, eliminating cold-start latency and per-visit API overhead.

**Architecture:** A new `builder.py` service computes and writes JSON files to `/data/static/` after every write operation. FastAPI handles writes only. nginx serves reads directly from `/data/static/`. The React frontend's `api/client.ts` is updated to fetch from `/static/` for all read operations.

**Tech Stack:** Python (FastAPI, SQLModel, httpx), TypeScript (React, React Query), nginx, Docker

---

## Task 1: `builder.py` — core data builder

**Files:**
- Create: `backend/app/services/builder.py`
- Create: `backend/tests/test_builder.py`

### Step 1: Write the failing tests

```python
# backend/tests/test_builder.py
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models import Activity, DataPoint, Goal, Shoe, TrainingPlan
from app.services.builder import rebuild_activity, rebuild_globals, rebuild_all, _tile_xy


@pytest.fixture
def act(session):
    a = Activity(
        source="manual_upload",
        started_at=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
        distance_m=10000.0,
        duration_s=3600,
        elevation_gain_m=100.0,
        sport_type="run",
    )
    session.add(a)
    session.flush()
    session.add(DataPoint(
        activity_id=a.id,
        timestamp=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
        lat=37.7749, lon=-122.4194, distance_m=0.0, speed_m_s=2.8,
    ))
    session.add(DataPoint(
        activity_id=a.id,
        timestamp=datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc),
        lat=37.7800, lon=-122.4100, distance_m=5000.0, speed_m_s=2.8,
    ))
    session.commit()
    session.refresh(a)
    return a


def test_tile_xy_known_value():
    # San Francisco at zoom 13: tile (1310, 3166)
    x, y = _tile_xy(37.7749, -122.4194, 13)
    assert x == 1310
    assert y == 3166


def test_rebuild_activity_writes_files(session, act, tmp_path):
    rebuild_activity(act.id, session, static_dir=tmp_path)

    activity_file = tmp_path / f"activity-{act.id}.json"
    datapoints_file = tmp_path / f"datapoints-{act.id}.json"

    assert activity_file.exists()
    assert datapoints_file.exists()

    data = json.loads(activity_file.read_text())
    assert data["activity"]["id"] == act.id
    assert data["activity"]["distance_m"] == 10000.0
    assert isinstance(data["laps"], list)
    assert len(data["track"]) == 2  # 2 GPS points
    assert data["track"][0] == [37.7749, -122.4194, 2.8]

    dps = json.loads(datapoints_file.read_text())
    assert len(dps) == 2
    assert dps[0]["activity_id"] == act.id


def test_rebuild_activity_missing_activity_is_noop(session, tmp_path):
    # Should not raise; file should not be created
    rebuild_activity(999, session, static_dir=tmp_path)
    assert not (tmp_path / "activity-999.json").exists()


def test_rebuild_globals_writes_all_files(session, act, tmp_path):
    rebuild_globals(session, static_dir=tmp_path)

    for filename in ["activities.json", "dashboard.json", "goals.json", "shoes.json", "plans.json"]:
        assert (tmp_path / filename).exists(), f"{filename} not found"

    acts = json.loads((tmp_path / "activities.json").read_text())
    assert len(acts) == 1
    assert acts[0]["id"] == act.id
    assert "track" in acts[0]

    dash = json.loads((tmp_path / "dashboard.json").read_text())
    assert "summary" in dash
    assert "week" in dash["summary"]
    assert "training_load" in dash
    assert "vdot" in dash
    assert "personal_bests" in dash


def test_rebuild_globals_empty_db(session, tmp_path):
    rebuild_globals(session, static_dir=tmp_path)
    acts = json.loads((tmp_path / "activities.json").read_text())
    assert acts == []


def test_rebuild_all(session, act, tmp_path):
    rebuild_all(session, static_dir=tmp_path, tile_dir=tmp_path / "tiles")

    assert (tmp_path / "activities.json").exists()
    assert (tmp_path / f"activity-{act.id}.json").exists()
    assert (tmp_path / f"datapoints-{act.id}.json").exists()
    assert (tmp_path / "dashboard.json").exists()
```

### Step 2: Run tests to verify they fail

```bash
cd /home/tim/projects/dromos/backend
python3 -m pytest tests/test_builder.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'app.services.builder'`

### Step 3: Implement `builder.py`

```python
# backend/app/services/builder.py
"""
Static JSON snapshot builder.

After every write (upload, delete, goal, shoe, plan), the relevant
snapshot files in STATIC_DIR are regenerated atomically. nginx serves
these files directly, so reads never touch Python.
"""
import json
import math
import os
from collections import defaultdict
from datetime import date, timedelta, datetime
from pathlib import Path

import httpx
from sqlmodel import Session, select, func

STATIC_DIR = Path(os.environ.get("DATA_DIR", "/data")) / "static"
TILE_DIR = Path(os.environ.get("DATA_DIR", "/data")) / "tiles"

PROVIDERS = {
    "light":    "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
    "standard": "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
    "dark":     "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
}
_TILE_HEADERS = {
    "User-Agent": "Dromos/1.0 (tile pre-fetcher)",
    "Accept": "image/png,image/*",
}
_PREFETCH_ZOOMS = range(12, 15)  # zooms 12–14; ~20–50 tiles per activity


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def _write_json(path: Path, data) -> None:
    """Atomic write: write to .tmp, then os.replace so nginx never serves partial."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, default=_json_default))
    tmp.replace(path)


def _downsample(points: list, max_points: int = 150) -> list:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    indices = {0, len(points) - 1}
    indices.update(int(i * step) for i in range(1, max_points - 1))
    return [points[i] for i in sorted(indices)]


def _tile_xy(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert lat/lon to OSM tile coordinates at the given zoom level."""
    lat_r = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


# ---------------------------------------------------------------------------
# Per-activity rebuild
# ---------------------------------------------------------------------------

def rebuild_activity(
    activity_id: int,
    session: Session,
    static_dir: Path = STATIC_DIR,
    tile_dir: Path = TILE_DIR,
) -> None:
    """Write activity-{id}.json, datapoints-{id}.json, and pre-fetch map tiles."""
    from app.models import Activity, DataPoint, Lap

    act = session.get(Activity, activity_id)
    if not act:
        return

    laps = session.exec(
        select(Lap).where(Lap.activity_id == activity_id).order_by(Lap.lap_number)
    ).all()

    dps = session.exec(
        select(DataPoint)
        .where(DataPoint.activity_id == activity_id)
        .order_by(DataPoint.timestamp)
    ).all()

    gps_rows = [(dp.lat, dp.lon, dp.speed_m_s) for dp in dps if dp.lat and dp.lon]
    track = [[lat, lon, spd] for lat, lon, spd in gps_rows]

    _write_json(static_dir / f"activity-{activity_id}.json", {
        "activity": act.model_dump(),
        "laps": [lap.model_dump() for lap in laps],
        "track": track,
    })
    _write_json(static_dir / f"datapoints-{activity_id}.json", [dp.model_dump() for dp in dps])

    if gps_rows:
        _prefetch_tiles(gps_rows, tile_dir)


def _prefetch_tiles(gps_rows: list, tile_dir: Path) -> None:
    """Best-effort: fetch and cache map tiles for a GPS track's bounding box."""
    lats = [r[0] for r in gps_rows]
    lons = [r[1] for r in gps_rows]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    try:
        with httpx.Client(timeout=8) as client:
            for zoom in _PREFETCH_ZOOMS:
                x_min, y_max = _tile_xy(min_lat, min_lon, zoom)
                x_max, y_min = _tile_xy(max_lat, max_lon, zoom)
                for x in range(x_min, x_max + 1):
                    for y in range(y_min, y_max + 1):
                        for provider, url_tpl in PROVIDERS.items():
                            cache_path = tile_dir / provider / str(zoom) / str(x) / f"{y}.png"
                            if cache_path.exists():
                                continue
                            try:
                                resp = client.get(url_tpl.format(z=zoom, x=x, y=y), headers=_TILE_HEADERS)
                                if resp.status_code == 200:
                                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                                    cache_path.write_bytes(resp.content)
                            except httpx.RequestError:
                                pass  # missed tile will be fetched on demand
    except Exception:
        pass  # tile pre-fetch is best-effort; never block a rebuild


# ---------------------------------------------------------------------------
# Global files rebuild
# ---------------------------------------------------------------------------

def rebuild_globals(session: Session, static_dir: Path = STATIC_DIR) -> None:
    """Rebuild activities.json, dashboard.json, goals.json, shoes.json, plans.json."""
    _rebuild_activities(session, static_dir)
    _rebuild_dashboard(session, static_dir)
    _rebuild_goals(session, static_dir)
    _rebuild_shoes(session, static_dir)
    _rebuild_plans(session, static_dir)


def _rebuild_activities(session: Session, static_dir: Path) -> None:
    from app.models import Activity, DataPoint, PlannedWorkout

    activities = session.exec(select(Activity).order_by(Activity.started_at.desc())).all()
    if not activities:
        _write_json(static_dir / "activities.json", [])
        return

    ids = [a.id for a in activities]

    gps_rows = session.exec(
        select(DataPoint.activity_id, DataPoint.lat, DataPoint.lon)
        .where(DataPoint.activity_id.in_(ids))
        .where(DataPoint.lat.is_not(None))
        .where(DataPoint.lon.is_not(None))
        .order_by(DataPoint.activity_id, DataPoint.timestamp)
    ).all()
    gps_by_id: dict[int, list] = defaultdict(list)
    for row in gps_rows:
        gps_by_id[row[0]].append([row[1], row[2]])

    planned = session.exec(
        select(PlannedWorkout.completed_activity_id, PlannedWorkout.workout_type)
        .where(PlannedWorkout.completed_activity_id.in_(ids))
    ).all()
    plan_type = {row[0]: row[1] for row in planned}

    result = []
    for a in activities:
        d = a.model_dump()
        d["track"] = _downsample(gps_by_id.get(a.id, []))
        d["planned_workout_type"] = plan_type.get(a.id)
        result.append(d)

    _write_json(static_dir / "activities.json", result)


def _rebuild_dashboard(session: Session, static_dir: Path) -> None:
    # Import stats functions directly; caches are already invalidated by the
    # write endpoint before this background task runs.
    from app.routers.stats import get_summary, get_training_load, get_vdot, get_personal_bests

    _write_json(static_dir / "dashboard.json", {
        "summary": {p: get_summary(period=p, session=session) for p in ("week", "month", "year", "all")},
        "training_load": get_training_load(days=365, session=session),
        "vdot": get_vdot(session=session),
        "personal_bests": get_personal_bests(session=session),
    })


def _rebuild_goals(session: Session, static_dir: Path) -> None:
    from app.models import Activity, Goal

    goals = session.exec(select(Goal)).all()
    result = []
    for g in goals:
        total = session.exec(
            select(func.sum(Activity.distance_m))
            .where(Activity.started_at >= g.period_start)
            .where(Activity.started_at < g.period_end + timedelta(days=1))
        ).first() or 0.0
        result.append({"goal": g.model_dump(), "progress_km": round(total / 1000, 2)})
    _write_json(static_dir / "goals.json", result)


def _rebuild_shoes(session: Session, static_dir: Path) -> None:
    from app.models import Activity, ActivityShoe, Shoe

    shoes = session.exec(select(Shoe)).all()
    result = []
    for shoe in shoes:
        dist = session.exec(
            select(func.sum(Activity.distance_m))
            .join(ActivityShoe, ActivityShoe.activity_id == Activity.id)
            .where(ActivityShoe.shoe_id == shoe.id)
        ).first() or 0.0
        result.append({**shoe.model_dump(), "total_distance_km": round(dist / 1000, 1)})
    _write_json(static_dir / "shoes.json", result)


def _rebuild_plans(session: Session, static_dir: Path) -> None:
    from app.models import PlannedWorkout, TrainingPlan

    plans = session.exec(select(TrainingPlan)).all()
    _write_json(static_dir / "plans.json", [p.model_dump() for p in plans])

    today = date.today()
    for plan in plans:
        workouts = session.exec(
            select(PlannedWorkout)
            .where(PlannedWorkout.training_plan_id == plan.id)
            .order_by(PlannedWorkout.scheduled_date)
        ).all()
        workout_list = []
        for w in workouts:
            if w.completed_activity_id:
                status = "completed"
            elif w.workout_type == "rest":
                status = "rest"
            elif w.scheduled_date < today:
                status = "missed"
            elif w.scheduled_date == today:
                status = "today"
            else:
                status = "future"
            workout_list.append({**w.model_dump(), "status": status})
        _write_json(static_dir / f"plan-{plan.id}.json", {
            "plan": plan.model_dump(),
            "workouts": workout_list,
        })


# ---------------------------------------------------------------------------
# Full rebuild
# ---------------------------------------------------------------------------

def rebuild_all(
    session: Session,
    static_dir: Path = STATIC_DIR,
    tile_dir: Path = TILE_DIR,
) -> None:
    """Rebuild every static file. Called on first startup or after Coros sync."""
    from app.models import Activity
    rebuild_globals(session, static_dir)
    for act in session.exec(select(Activity)).all():
        rebuild_activity(act.id, session, static_dir, tile_dir)


# ---------------------------------------------------------------------------
# Background-task-safe wrappers (open their own sessions)
# These are passed to FastAPI BackgroundTasks, which run after the response
# is sent — the request-scoped session is closed by then.
# ---------------------------------------------------------------------------

def _new_session():
    from app.database import Session as _Session, engine
    return _Session(engine)


def bg_rebuild_after_upload(activity_id: int) -> None:
    """Call after a new activity is added."""
    try:
        with _new_session() as session:
            rebuild_activity(activity_id, session)
            rebuild_globals(session)
    except Exception as exc:
        print(f"[builder] bg_rebuild_after_upload failed: {exc}")


def bg_rebuild_after_delete(activity_id: int) -> None:
    """Call after an activity is deleted. Removes per-activity files, rebuilds globals."""
    try:
        for name in (f"activity-{activity_id}.json", f"datapoints-{activity_id}.json"):
            (STATIC_DIR / name).unlink(missing_ok=True)
        with _new_session() as session:
            rebuild_globals(session)
    except Exception as exc:
        print(f"[builder] bg_rebuild_after_delete failed: {exc}")


def bg_rebuild_after_activity_update(activity_id: int) -> None:
    """Call after notes/rpe/strava_id updated — only rebuilds activity files."""
    try:
        with _new_session() as session:
            rebuild_activity(activity_id, session)
            _rebuild_activities(session, STATIC_DIR)
    except Exception as exc:
        print(f"[builder] bg_rebuild_after_activity_update failed: {exc}")


def bg_rebuild_globals() -> None:
    """Call after goal/shoe/plan changes."""
    try:
        with _new_session() as session:
            rebuild_globals(session)
    except Exception as exc:
        print(f"[builder] bg_rebuild_globals failed: {exc}")


def bg_rebuild_all() -> None:
    """Call after Coros sync completes."""
    try:
        with _new_session() as session:
            rebuild_all(session)
    except Exception as exc:
        print(f"[builder] bg_rebuild_all failed: {exc}")
```

### Step 4: Run tests to verify they pass

```bash
cd /home/tim/projects/dromos/backend
python3 -m pytest tests/test_builder.py -v
```

Expected: all 6 tests pass. (`test_tile_xy_known_value`, `test_rebuild_activity_writes_files`, `test_rebuild_activity_missing_activity_is_noop`, `test_rebuild_globals_writes_all_files`, `test_rebuild_globals_empty_db`, `test_rebuild_all`)

### Step 5: Run the full test suite to check for regressions

```bash
python3 -m pytest -v 2>&1 | tail -20
```

Expected: all previously passing tests still pass.

### Step 6: Commit

```bash
cd /home/tim/projects/dromos
git add backend/app/services/builder.py backend/tests/test_builder.py
git commit -m "feat: add static JSON snapshot builder service"
```

---

## Task 2: Hook builder into write endpoints

**Files:**
- Modify: `backend/app/routers/activities.py`
- Modify: `backend/app/routers/goals.py`
- Modify: `backend/app/routers/shoes.py`
- Modify: `backend/app/routers/plans.py`
- Modify: `backend/app/routers/sync.py`

Add `BackgroundTasks` to each write endpoint and schedule the appropriate `bg_*` function.

### Step 1: Update `activities.py`

At the top, add the import:
```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks
from app.services.builder import bg_rebuild_after_upload, bg_rebuild_after_delete, bg_rebuild_after_activity_update
```

Update `upload_fit` signature and body:
```python
@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_fit(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    # ... existing logic unchanged ...
    session.commit()
    session.refresh(act)
    _invalidate_list_cache()
    from app.routers.stats import _invalidate_pb_cache, _invalidate_stats_cache
    _invalidate_pb_cache()
    _invalidate_stats_cache()
    background_tasks.add_task(bg_rebuild_after_upload, act.id)  # ADD THIS LINE
    return act
```

Update `delete_activity`:
```python
@router.delete("/{activity_id}", status_code=204)
def delete_activity(activity_id: int, background_tasks: BackgroundTasks = BackgroundTasks(), session: Session = Depends(get_session)):
    # ... existing logic ...
    session.commit()
    _invalidate_list_cache()
    from app.routers.stats import _invalidate_pb_cache, _invalidate_stats_cache
    _invalidate_pb_cache()
    _invalidate_stats_cache()
    background_tasks.add_task(bg_rebuild_after_delete, activity_id)  # ADD THIS LINE
```

Update `update_activity`:
```python
@router.patch("/{activity_id}")
def update_activity(
    activity_id: int,
    data: dict,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    # ... existing logic ...
    session.commit()
    session.refresh(act)
    background_tasks.add_task(bg_rebuild_after_activity_update, activity_id)  # ADD THIS LINE
    return act
```

**Note on `BackgroundTasks()` default:** FastAPI automatically injects a real `BackgroundTasks` instance when the endpoint is called via HTTP. The `BackgroundTasks()` default is only needed to prevent a type error when calling the function directly in tests (tests that don't pass this parameter). Alternatively, omit the default and update test calls accordingly.

### Step 2: Update `goals.py`

Add imports:
```python
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.services.builder import bg_rebuild_globals
```

Add to `create_goal`, `update_goal`, `delete_goal`:
```python
# In each endpoint signature, add: background_tasks: BackgroundTasks = BackgroundTasks()
# At the end of each endpoint body, before return:
background_tasks.add_task(bg_rebuild_globals)
```

### Step 3: Update `shoes.py`

Same pattern as goals:
```python
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.services.builder import bg_rebuild_globals
# Add background_tasks param + add_task(bg_rebuild_globals) to create_shoe and update_shoe
```

### Step 4: Update `plans.py`

Same pattern. `create_plan` and `delete_plan` rebuild globals. `update_workout` (marking a workout complete) rebuilds the specific plan file plus activities (plan-activity link changes):
```python
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.services.builder import bg_rebuild_globals

# In update_workout, rebuild the plan detail + activities list
# (plan status "completed" affects the plan page, and goals progress may change)
background_tasks.add_task(bg_rebuild_globals)
```

### Step 5: Update `sync.py`

After `_sync_coros` and `_sync_strava_photos` complete, trigger a full rebuild:
```python
from app.services.builder import bg_rebuild_all

@router.post("/trigger")
def trigger(bg: BackgroundTasks, session: Session = Depends(get_session)):
    bg.add_task(_sync_strava_photos, session)
    bg.add_task(_sync_coros, session)
    bg.add_task(bg_rebuild_all)   # ADD THIS LINE
    return {"message": "sync triggered"}
```

### Step 6: Run full test suite

```bash
cd /home/tim/projects/dromos/backend
python3 -m pytest -v 2>&1 | tail -20
```

Expected: all tests pass (background tasks run in TestClient but builder writes to STATIC_DIR which silently fails or succeeds — both are acceptable).

### Step 7: Commit

```bash
cd /home/tim/projects/dromos
git add backend/app/routers/activities.py backend/app/routers/goals.py \
        backend/app/routers/shoes.py backend/app/routers/plans.py \
        backend/app/routers/sync.py
git commit -m "feat: trigger static rebuild after every write operation"
```

---

## Task 3: Startup rebuild in `main.py`

**Files:**
- Modify: `backend/app/main.py`

### Step 1: Update the lifespan function

In `main.py`, replace `_warm_all_caches` with a combined warm+build startup function:

```python
def _startup_rebuild():
    """
    On first startup (no activities.json), run a full rebuild synchronously.
    On subsequent starts, just warm the in-process TTL caches.
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
            # Files exist; just warm the in-process caches
            warm_activities(session)
            warm_stats(session)
```

Replace the existing `threading.Thread(target=_warm_all_caches, daemon=True).start()` line with:
```python
threading.Thread(target=_startup_rebuild, daemon=True).start()
```

### Step 2: Run the test suite to confirm no regressions

```bash
cd /home/tim/projects/dromos/backend
python3 -m pytest -v 2>&1 | tail -20
```

### Step 3: Commit

```bash
cd /home/tim/projects/dromos
git add backend/app/main.py
git commit -m "feat: startup rebuild when static files are absent"
```

---

## Task 4: nginx — add `/static/` location

**Files:**
- Modify: `frontend/nginx.conf`

### Step 1: Add the `/static/` location block

In `nginx.conf`, insert this block after the `/assets/` block and before the `/api/` block:

```nginx
# Pre-built static JSON snapshots — reads never hit Python
location /static/ {
    alias /data/static/;
    add_header Cache-Control "no-cache";
    default_type application/json;
    gzip_static on;
}
```

The `no-cache` header means the browser sends a conditional GET (ETag/If-Modified-Since) on every load, but gets a 304 Not Modified response if the file hasn't changed — effectively zero-cost after the first fetch.

### Step 2: Verify the nginx config is valid

```bash
docker run --rm -v /home/tim/projects/dromos/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro nginx:alpine nginx -t
```

Expected: `nginx: configuration file /etc/nginx/nginx.conf test is successful`

### Step 3: Commit

```bash
cd /home/tim/projects/dromos
git add frontend/nginx.conf
git commit -m "feat: nginx serves /static/ JSON snapshots from /data/static/"
```

---

## Task 5: docker-compose — share `/data` with frontend container

**Files:**
- Modify: `docker-compose.yml`

### Step 1: Add volume mount to frontend service

Current `docker-compose.yml` frontend section:
```yaml
frontend:
  build: ./frontend
  ports:
    - "80:80"
  depends_on:
    - backend
  restart: unless-stopped
```

Updated:
```yaml
frontend:
  build: ./frontend
  ports:
    - "80:80"
  volumes:
    - ./data:/data
  depends_on:
    - backend
  restart: unless-stopped
```

The `./data:/data` volume is already present on the backend service; adding it to the frontend lets nginx read from `/data/static/`.

### Step 2: Commit

```bash
cd /home/tim/projects/dromos
git add docker-compose.yml
git commit -m "feat: mount /data volume in frontend container for static file serving"
```

---

## Task 6: Frontend — update `api/client.ts` reads to use `/static/`

**Files:**
- Modify: `frontend/src/api/client.ts`

### Step 1: Replace read functions

The write functions (`uploadFit`, `updateActivity`, `createGoal`, etc.) stay on `axios` pointing to `/api/`. All read functions switch to `fetch("/static/...")`.

The key changes:

```typescript
import axios from "axios";

const api = axios.create({ baseURL: "/api" });

// ── static reads (served by nginx from /data/static/) ─────────────────────

const _fetchJson = (url: string) => fetch(url).then((r) => {
  if (!r.ok) throw new Error(`Static fetch failed: ${r.status} ${url}`);
  return r.json();
});

export const getActivities = () => _fetchJson("/static/activities.json");

export const getActivityFull = (id: number) =>
  _fetchJson(`/static/activity-${id}.json`);

export const getDataPoints = (id: number) =>
  _fetchJson(`/static/datapoints-${id}.json`);

// Stats/dashboard: all come from one file; each function extracts its slice.
export const getStatsSummary = (period = "week") =>
  _fetchJson("/static/dashboard.json").then((d) => d.summary[period]);

export const getTrainingLoad = (days = 90) =>
  _fetchJson("/static/dashboard.json").then((d: { training_load: { date: string }[] }) => {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    return d.training_load.filter((row) => new Date(row.date) >= cutoff);
  });

export const getVdot = () =>
  _fetchJson("/static/dashboard.json").then((d) => d.vdot);

export const getPersonalBests = () =>
  _fetchJson("/static/dashboard.json").then((d) => d.personal_bests);

export const getGoals = () => _fetchJson("/static/goals.json");

export const getShoes = () => _fetchJson("/static/shoes.json");

export const getPlans = () => _fetchJson("/static/plans.json");

export const getPlan = (id: number) =>
  _fetchJson(`/static/plan-${id}.json`).then((d) => d.plan);

export const getPlanWorkouts = (id: number) =>
  _fetchJson(`/static/plan-${id}.json`).then((d) => d.workouts);

// ── write operations (still go through FastAPI) ───────────────────────────

export const getActivity = (id: number) =>
  api.get(`/activities/${id}`).then((r) => r.data);

export const uploadFit = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return api.post("/activities/upload", fd).then((r) => r.data);
};

export const updateActivity = (id: number, data: object) =>
  api.patch(`/activities/${id}`, data).then((r) => r.data);

export const deleteActivity = (id: number) => api.delete(`/activities/${id}`);

export const createGoal = (data: object) =>
  api.post("/goals", data).then((r) => r.data);

export const updateGoal = (id: number, data: object) =>
  api.put(`/goals/${id}`, data).then((r) => r.data);

export const deleteGoal = (id: number) => api.delete(`/goals/${id}`);

export const createShoe = (data: object) =>
  api.post("/shoes", data).then((r) => r.data);

export const updateShoe = (id: number, data: object) =>
  api.patch(`/shoes/${id}`, data).then((r) => r.data);

export const createPlan = (data: object) =>
  api.post("/plans", data).then((r) => r.data);

export const deletePlan = (id: number) => api.delete(`/plans/${id}`);

export const updatePlanWorkout = (planId: number, workoutId: number, data: object) =>
  api.patch(`/plans/${planId}/workouts/${workoutId}`, data).then((r) => r.data);

export const getSyncStatus = () => api.get("/sync/status").then((r) => r.data);
export const triggerSync = () => api.post("/sync/trigger").then((r) => r.data);

export const getActivityAnalytics = (id: number) =>
  api.get(`/stats/activities/${id}/analytics`).then((r) => r.data);

export const getPhotos = (id: number) =>
  api.get(`/activities/${id}/photos`).then((r) => r.data);
```

**Removed functions** (subsumed into combined static reads):
- `getTrack` — track is now included in `activity-{id}.json`
- `getLaps` — laps are now included in `activity-{id}.json`

### Step 2: Update `staleTime` on static reads

Since static files only change after explicit writes, set `staleTime: Infinity` in any `useQuery` call that reads from static. Grep for existing staleTime settings:

```bash
grep -rn "staleTime" /home/tim/projects/dromos/frontend/src/
```

The existing `staleTime: 5 * 60_000` and `staleTime: 60_000` values can be updated to `staleTime: Infinity` for all static reads. This makes React Query never refetch in the background — data updates only after a mutation triggers `invalidateQueries`.

### Step 3: Check the TypeScript build passes

```bash
cd /home/tim/projects/dromos/frontend
npm run build 2>&1 | tail -20
```

Expected: build succeeds with no TypeScript errors.

### Step 4: Commit

```bash
cd /home/tim/projects/dromos
git add frontend/src/api/client.ts
git commit -m "feat: frontend reads from /static/ JSON snapshots instead of live API"
```

---

## Task 7: Build and verify end-to-end

### Step 1: Build both Docker images

```bash
cd /home/tim/projects/dromos
docker build -t dromos-backend ./backend
docker build -t dromos-frontend ./frontend
```

Expected: both builds succeed with no errors.

### Step 2: Deploy

```bash
docker compose down && docker compose up -d
```

### Step 3: Verify static files are generated

```bash
sleep 5  # give backend a moment to run startup rebuild
ls -lh /home/tim/projects/dromos/data/static/
```

Expected: `activities.json`, `dashboard.json`, `goals.json`, `shoes.json`, `plans.json` present.

### Step 4: Verify nginx serves static files

```bash
curl -si http://localhost/static/activities.json | head -5
```

Expected: `HTTP/1.1 200 OK` with `Content-Type: application/json`.

### Step 5: Verify a write triggers a rebuild

Upload a `.fit` file via the UI (or curl), wait 3 seconds, then verify `activities.json` updated:

```bash
stat /home/tim/projects/dromos/data/static/activities.json
```

Timestamp should be within the last few seconds.

### Step 6: Run the backend test suite one final time

```bash
cd /home/tim/projects/dromos/backend
python3 -m pytest -v 2>&1 | tail -10
```

Expected: all 58+ tests pass.

### Step 7: Final commit if any adjustments were needed

```bash
cd /home/tim/projects/dromos
git add -p  # stage any fixup changes
git commit -m "fix: end-to-end verification adjustments"
```

---

## Notes

- **Backward compatibility:** The `/api/` read endpoints still exist and still work. The frontend simply stops calling them. They can be removed in a future cleanup pass.
- **`getLaps` and `getTrack`** are removed from `client.ts` since laps and track are embedded in `activity-{id}.json`. Any component using them directly (e.g. `ActivityDetail`) reads from `getActivityFull` which already returns all three.
- **Tile pre-fetch** is best-effort and non-blocking. Tiles not pre-fetched on upload are still fetched on demand by the tiles router (unchanged behavior).
- **After sync:** the full rebuild includes tile pre-fetch for all activities, which may take several minutes for a large library. This is fine since sync itself is a background operation.
