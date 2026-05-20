"""
Static JSON snapshot builder.

After every write (upload, delete, goal, shoe), the relevant snapshot
files in STATIC_DIR are regenerated atomically. nginx serves these
files directly, so reads never touch Python.
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
    "User-Agent": "RunScribe/1.0 (tile pre-fetcher)",
    "Accept": "image/png,image/*",
}
_PREFETCH_ZOOMS = range(12, 15)  # zooms 12-14; ~20-50 tiles per activity


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _json_default(obj):
    if isinstance(obj, datetime):
        # Naive datetimes are always UTC — append Z so browsers parse them correctly.
        if obj.tzinfo is None:
            return obj.isoformat() + "Z"
        return obj.isoformat()
    if isinstance(obj, date):
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


# ──────────────────────────────────────────────────────────────────────────
# Period volume bucketing helpers
# ──────────────────────────────────────────────────────────────────────────

_WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _bucket_by_day(acts, start: date, end: date, label_style: str) -> list[dict]:
    """
    One bucket per calendar day in [start, end] inclusive.

    label_style:
      - "weekday"       — "Sun".."Sat" (used by last_7_days view)
      - "day_of_month"  — "1".."31"    (used by month view)
    """
    n_days = (end - start).days + 1
    by_date: dict[date, float] = {}
    for a in acts:
        d = a.started_at.date()
        if start <= d <= end:
            by_date[d] = by_date.get(d, 0.0) + a.distance_m

    buckets = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        if label_style == "weekday":
            label = _WEEKDAY_SHORT[d.weekday()]
        elif label_style == "day_of_month":
            label = str(d.day)
        else:
            raise ValueError(f"unknown label_style: {label_style}")
        buckets.append({
            "date": d.isoformat(),
            "label": label,
            "km": round(by_date.get(d, 0.0) / 1000.0, 2),
        })
    return buckets


def _sunday_on_or_before(d: date) -> date:
    """Return the Sunday on or before d. Python: weekday() Mon=0..Sun=6."""
    days_since_sun = (d.weekday() + 1) % 7   # Sun=0, Mon=1, ... Sat=6
    return d - timedelta(days=days_since_sun)


def _bucket_by_week_sun_start(acts, start: date, end: date) -> list[dict]:
    """
    Sunday-start weekly buckets covering [start, end].

    The first bucket's date is the Sunday on or before `start`.
    The bucket's `label` is the first calendar date in [start, end] that
    falls in that week (e.g. "Jan 1" if year starts mid-week).
    Only activities with date in [start, end] count toward km totals.
    """
    first_sun = _sunday_on_or_before(start)
    buckets = []
    cur = first_sun
    while cur <= end:
        week_end = cur + timedelta(days=6)
        clamp_lo = max(cur, start)
        clamp_hi = min(week_end, end)
        total_m = 0.0
        for a in acts:
            d = a.started_at.date()
            if clamp_lo <= d <= clamp_hi:
                total_m += a.distance_m
        label_date = clamp_lo
        label = f"{label_date.strftime('%b')} {label_date.day}"
        buckets.append({
            "date": cur.isoformat(),
            "label": label,
            "km": round(total_m / 1000.0, 2),
        })
        cur += timedelta(days=7)
    return buckets


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
    from app.models import Activity, ActivityShoe, DataPoint, Lap, Shoe

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

    shoes = session.exec(
        select(Shoe)
        .join(ActivityShoe, ActivityShoe.shoe_id == Shoe.id)
        .where(ActivityShoe.activity_id == activity_id)
    ).all()

    gps_rows = [(dp.lat, dp.lon, dp.speed_m_s) for dp in dps if dp.lat and dp.lon]
    track = [[lat, lon, spd] for lat, lon, spd in gps_rows]

    _write_json(static_dir / f"activity-{activity_id}.json", {
        "activity": act.model_dump(),
        "laps": [lap.model_dump() for lap in laps],
        "track": track,
        "shoes": [{"id": s.id, "name": s.name, "brand": s.brand} for s in shoes],
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
                                pass
    except Exception:
        pass  # tile pre-fetch is best-effort; never block a rebuild


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

_MILE_M = 1609.344


def _compute_eddington(daily_miles: dict[str, float]) -> dict:
    """
    Compute current Eddington number and its growth history.
    daily_miles: {date_iso_str: total_miles_that_day}
    Returns: {current_e, next_e_gap, history: [{date, e}]}
    """
    if not daily_miles:
        return {"current_e": 0, "next_e_gap": 1, "history": []}

    sorted_days = sorted(daily_miles.items())  # chronological
    max_miles = int(max(daily_miles.values())) + 2

    # counts[n] = number of days with distance >= n miles (1-indexed)
    counts = [0] * (max_miles + 1)
    current_e = 0
    history: list[dict] = []

    for day_str, miles in sorted_days:
        n = min(int(miles), max_miles)
        for i in range(1, n + 1):
            counts[i] += 1
        # Advance E as far as possible
        while current_e + 1 <= max_miles and counts[current_e + 1] >= current_e + 1:
            current_e += 1
            history.append({"date": day_str, "e": current_e})

    next_e_gap = (current_e + 1) - counts[current_e + 1] if current_e + 1 <= max_miles else 1
    return {
        "current_e": current_e,
        "next_e_gap": max(0, next_e_gap),
        "history": history,
    }


def _compute_yearly(acts: list[dict]) -> dict:
    """
    Collect activity distances by calendar year and day-of-year.
    One entry per activity so the cumulative chart steps at each workout.
    acts: list of dicts with 'started_at' (ISO str or datetime) and 'distance_m'.
    Returns: {years: {str_year: [{day, km}]}}
    """
    from collections import defaultdict
    by_year: dict[str, list[dict]] = defaultdict(list)

    for a in acts:
        started = a["started_at"]
        if isinstance(started, str):
            dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        else:
            dt = started
        year = str(dt.year)
        day = dt.timetuple().tm_yday   # 1-366
        by_year[year].append({"day": day, "km": round(a["distance_m"] / 1000.0, 2)})

    years_out = {}
    for year, entries in sorted(by_year.items()):
        years_out[year] = sorted(entries, key=lambda e: e["day"])
    return {"years": years_out}


def _rebuild_metrics(session: Session, static_dir: Path) -> None:
    from app.models import Activity
    from collections import defaultdict

    acts = session.exec(
        select(Activity).order_by(Activity.started_at)
    ).all()

    # Aggregate distance per calendar day (miles)
    daily: dict[str, float] = defaultdict(float)
    for a in acts:
        day = a.started_at.date().isoformat()
        daily[day] += a.distance_m / _MILE_M

    act_dicts = [{"started_at": a.started_at, "distance_m": a.distance_m} for a in acts]

    _write_json(static_dir / "metrics.json", {
        "eddington": _compute_eddington(dict(daily)),
        "yearly": _compute_yearly(act_dicts),
    })


# ---------------------------------------------------------------------------
# Global files rebuild
# ---------------------------------------------------------------------------

def rebuild_globals(session: Session, static_dir: Path = STATIC_DIR) -> None:
    """Rebuild activities.json, dashboard.json, goals.json, shoes.json, metrics.json."""
    _rebuild_activities(session, static_dir)
    _rebuild_dashboard(session, static_dir)
    _rebuild_goals(session, static_dir)
    _rebuild_shoes(session, static_dir)
    _rebuild_metrics(session, static_dir)


def _rebuild_activities(session: Session, static_dir: Path) -> None:
    from app.models import Activity, ActivityShoe, DataPoint, Shoe

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

    shoe_rows = session.exec(
        select(ActivityShoe.activity_id, Shoe.name)
        .join(Shoe, Shoe.id == ActivityShoe.shoe_id)
        .where(ActivityShoe.activity_id.in_(ids))
    ).all()
    shoes_by_id: dict[int, list] = defaultdict(list)
    for row in shoe_rows:
        shoes_by_id[row[0]].append(row[1])

    result = []
    for a in activities:
        d = a.model_dump()
        d["track"] = _downsample(gps_by_id.get(a.id, []))
        d["shoe_names"] = shoes_by_id.get(a.id, [])
        result.append(d)

    _write_json(static_dir / "activities.json", result)


def _rebuild_dashboard(session: Session, static_dir: Path) -> None:
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

    rows = session.exec(
        select(ActivityShoe.shoe_id, Activity.started_at, Activity.distance_m, Activity.id)
        .join(Activity, ActivityShoe.activity_id == Activity.id)
        .order_by(ActivityShoe.shoe_id, Activity.started_at)
    ).all()

    timelines: dict[int, list[dict]] = defaultdict(list)
    years: dict[int, set[int]] = defaultdict(set)
    act_ids: dict[int, list[int]] = defaultdict(list)
    cum_m: dict[int, float] = defaultdict(float)
    for shoe_id, started_at, distance_m, activity_id in rows:
        cum_m[shoe_id] += distance_m or 0.0
        timelines[shoe_id].append({
            "date": started_at.date().isoformat(),
            "cumulative_km": round(cum_m[shoe_id] / 1000, 1),
        })
        years[shoe_id].add(started_at.year)
        act_ids[shoe_id].append(activity_id)

    result = []
    for shoe in shoes:
        result.append({
            **shoe.model_dump(),
            "total_distance_km": round(cum_m.get(shoe.id, 0.0) / 1000, 1),
            "activity_ids": sorted(act_ids.get(shoe.id, []), reverse=True),
            "timeline": timelines.get(shoe.id, []),
            "years": sorted(years.get(shoe.id, [])),
        })
    _write_json(static_dir / "shoes.json", result)


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


def bg_rebuild_after_delete(activity_id: int, static_dir: Path = STATIC_DIR) -> None:
    """Call after an activity is deleted. Removes per-activity files, rebuilds globals."""
    try:
        for name in (f"activity-{activity_id}.json", f"datapoints-{activity_id}.json"):
            (static_dir / name).unlink(missing_ok=True)
        with _new_session() as session:
            rebuild_globals(session, static_dir)
    except Exception as exc:
        print(f"[builder] bg_rebuild_after_delete failed: {exc}")


def bg_rebuild_after_activity_update(activity_id: int, static_dir: Path = STATIC_DIR) -> None:
    """Call after notes/rpe/strava_id updated."""
    try:
        with _new_session() as session:
            rebuild_activity(activity_id, session, static_dir=static_dir)
            _rebuild_activities(session, static_dir)
    except Exception as exc:
        print(f"[builder] bg_rebuild_after_activity_update failed: {exc}")


def bg_rebuild_globals() -> None:
    """Call after goal/shoe changes."""
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
