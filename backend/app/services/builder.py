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
    "User-Agent": "Dromos/1.0 (tile pre-fetcher)",
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
    """Atomic write: write to .tmp, then os.replace so readers never see partial.

    Also emits a Brotli-precompressed ``<path>.br`` sibling so the static mount
    can serve it directly with ``Content-Encoding: br`` to capable clients.
    """
    from app.services.precompress import write_br

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, default=_json_default).encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)
    write_br(path, payload)


def _downsample(points: list, max_points: int = 150) -> list:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    indices = {0, len(points) - 1}
    indices.update(int(i * step) for i in range(1, max_points - 1))
    return [points[i] for i in sorted(indices)]


# Bump when the *shape* of any emitted JSON changes, so deploys onto an existing
# data volume know to do a full rebuild (per-activity files aren't covered by the
# globals-only refresh). v2: trimmed activities.json + downsampled track/datapoints.
# v3: added sunrise/sunset to activity-{id}.json.
# v4: Brotli .br siblings — force a full rebuild so per-activity files get one.
STATIC_SCHEMA_VERSION = "4"


def static_schema_is_current(static_dir: Path = STATIC_DIR) -> bool:
    vf = static_dir / ".schema_version"
    return vf.is_file() and vf.read_text().strip() == STATIC_SCHEMA_VERSION


# ── Payload tuning ───────────────────────────────────────────────────────────
# Coordinate precision: 5 decimals ≈ 1.1 m, far finer than any rendering here.
_COORD_PREC = 5
# Thumbnail routes (112×84px) need only a coarse outline.
_THUMB_TRACK_POINTS = 48
# Detail map polyline: ~one point every few metres is plenty for a route line.
_MAP_TRACK_POINTS = 2000
# Per-activity chart series: hover/lines stay crisp well below full FIT density.
_CHART_DATAPOINTS = 2000

# Activity fields the list/dashboard/calendar/compare-picker actually render.
# Everything else (weather_*, fit_file_path, strava_id, elevation_*, source…)
# is detail-only and lives in activity-{id}.json, not the eager list payload.
_LIST_FIELDS = (
    "id", "name", "started_at", "distance_m", "duration_s",
    "avg_pace_s_per_km", "avg_hr", "rpe", "sport_type", "notes",
)


def _thumb_track(points: list) -> list:
    """Coarse, low-precision [lat, lon] outline for list/dashboard thumbnails."""
    return [
        [round(lat, _COORD_PREC), round(lon, _COORD_PREC)]
        for lat, lon in _downsample(points, _THUMB_TRACK_POINTS)
    ]


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

    First bucket's date is the Sunday on or before `start`.
    Label is the first calendar date in [start, end] that falls in that week
    (e.g., "Jan 1" if year starts mid-week). Only activities with date in
    [start, end] count toward km totals.
    """
    by_date: dict[date, float] = {}
    for a in acts:
        d = a.started_at.date()
        if start <= d <= end:
            by_date[d] = by_date.get(d, 0.0) + a.distance_m

    first_sun = _sunday_on_or_before(start)
    buckets = []
    cur = first_sun
    while cur <= end:
        week_end = cur + timedelta(days=6)
        clamp_lo = max(cur, start)
        clamp_hi = min(week_end, end)
        total_m = 0.0
        d = clamp_lo
        while d <= clamp_hi:
            total_m += by_date.get(d, 0.0)
            d += timedelta(days=1)
        label = f"{clamp_lo.strftime('%b')} {clamp_lo.day}"
        buckets.append({
            "date": cur.isoformat(),
            "label": label,
            "km": round(total_m / 1000.0, 2),
        })
        cur += timedelta(days=7)
    return buckets


def _weighted_avg_pace_s_per_km(acts) -> float | None:
    total_km = sum(a.distance_m for a in acts) / 1000.0
    total_s = sum(a.duration_s for a in acts)
    if total_km <= 0:
        return None
    return round(total_s / total_km, 1)


def _compute_period_data(acts, period: str, today: date) -> tuple[dict, dict]:
    """
    Compute (summary, volume) for one period.

    Invariant: summary["total_distance_km"] == volume["total_km"].
    """
    if period == "last_7_days":
        start = today - timedelta(days=6)
        end = today
        label_style = "weekday"
        weekly = False
    elif period == "month":
        start = today.replace(day=1)
        if start.month == 12:
            end = date(start.year, 12, 31)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        label_style = "day_of_month"
        weekly = False
    elif period == "year":
        start = date(today.year, 1, 1)
        end = date(today.year, 12, 31)
        weekly = True
    else:
        raise ValueError(f"unknown period: {period}")

    in_period = [a for a in acts if start <= a.started_at.date() <= end]
    total_km = round(sum(a.distance_m for a in in_period) / 1000.0, 2)

    summary = {
        "period": period,
        "count": len(in_period),
        "total_distance_km": total_km,
        "total_duration_s": sum(a.duration_s for a in in_period),
        "total_elevation_m": round(sum(a.elevation_gain_m or 0 for a in in_period), 1),
        "avg_pace_s_per_km": _weighted_avg_pace_s_per_km(in_period),
    }

    if weekly:
        buckets = _bucket_by_week_sun_start(in_period, start, end)
    else:
        buckets = _bucket_by_day(in_period, start, end, label_style)

    volume = {"buckets": buckets, "total_km": total_km}
    return summary, volume


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
    # Map polyline: downsample + round. Full FIT density (~7k pts) is invisible
    # at any map zoom and dominates the detail payload.
    track = [
        [round(lat, _COORD_PREC), round(lon, _COORD_PREC),
         round(spd, 3) if spd is not None else None]
        for lat, lon, spd in _downsample(gps_rows, _MAP_TRACK_POINTS)
    ]

    _write_json(static_dir / f"activity-{activity_id}.json", {
        "activity": act.model_dump(),
        "laps": [lap.model_dump() for lap in laps],
        "track": track,
        "shoes": [{"id": s.id, "name": s.name, "brand": s.brand} for s in shoes],
    })
    # Chart series: downsample rows (keeps every field, ~3.5× fewer points).
    _write_json(
        static_dir / f"datapoints-{activity_id}.json",
        [dp.model_dump() for dp in _downsample(dps, _CHART_DATAPOINTS)],
    )

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
        full = a.model_dump()
        d = {k: full[k] for k in _LIST_FIELDS}
        d["track"] = _thumb_track(gps_by_id.get(a.id, []))
        d["shoe_names"] = shoes_by_id.get(a.id, [])
        result.append(d)

    _write_json(static_dir / "activities.json", result)


def _today_fn() -> date:
    """Indirection so tests can freeze 'today' via monkeypatch."""
    return date.today()


def _rebuild_dashboard(session: Session, static_dir: Path) -> None:
    from app.services.stats import get_training_load, get_vdot, get_personal_bests
    from app.models import Activity

    acts = session.exec(select(Activity)).all()
    today = _today_fn()

    summary = {}
    volume = {}
    for p in ("last_7_days", "month", "year"):
        s, v = _compute_period_data(acts, p, today)
        summary[p] = s
        volume[p] = v

    _write_json(static_dir / "dashboard.json", {
        "summary": summary,
        "volume": volume,
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
    """Emit two files:

    - ``shoes.json``: array of per-shoe metadata (retained shape, consumed by
      ActivityList/ActivityDetail/Gear); each entry now also exposes
      ``first_used`` for chart-line origin styling.
    - ``shoes_timeline.json``: ``[{date, "<shoe_id>": cum_km, ...}, ...]`` — a
      dense day-aligned series from the earliest first-use across all shoes
      through today, with carry-forward on rest days and post-retirement.
      Values are ``null`` before that shoe's own first use, so each line
      starts at its own entry point rather than the axis origin.
    """
    from app.models import Activity, ActivityShoe, Shoe, UserProfile

    shoes = session.exec(select(Shoe)).all()
    profile = session.get(UserProfile, 1)
    default_id = profile.default_shoe_id if profile else None

    rows = session.exec(
        select(ActivityShoe.shoe_id, Activity.started_at, Activity.distance_m, Activity.id)
        .join(Activity, ActivityShoe.activity_id == Activity.id)
        .order_by(ActivityShoe.shoe_id, Activity.started_at)
    ).all()

    per_day_m: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    first_day: dict[int, date] = {}
    act_ids: dict[int, list[int]] = defaultdict(list)
    total_m: dict[int, float] = defaultdict(float)
    for shoe_id, started_at, distance_m, activity_id in rows:
        d = started_at.date()
        dist = distance_m or 0.0
        per_day_m[shoe_id][d] += dist
        first_day.setdefault(shoe_id, d)
        act_ids[shoe_id].append(activity_id)
        total_m[shoe_id] += dist

    if first_day:
        axis_start = min(first_day.values())
        axis_end = date.today()
        days = [axis_start + timedelta(days=i)
                for i in range((axis_end - axis_start).days + 1)]
    else:
        days = []

    daily: list[dict] = [{"date": d.isoformat()} for d in days]
    for shoe in shoes:
        if shoe.id not in first_day:
            continue
        key = str(shoe.id)
        fd = first_day[shoe.id]
        # For retired shoes, terminate the line on the last activity day
        # (we don't store a retirement timestamp — last use is the proxy).
        last_day = max(per_day_m[shoe.id].keys()) if shoe.retired else None
        cum_km = 0.0
        for i, d in enumerate(days):
            if d < fd:
                daily[i][key] = None
                continue
            if last_day is not None and d > last_day:
                daily[i][key] = None
                continue
            cum_km += per_day_m[shoe.id].get(d, 0.0) / 1000
            daily[i][key] = round(cum_km, 2)

    shoes_meta = [{
        **shoe.model_dump(),
        "total_distance_km": round(total_m.get(shoe.id, 0.0) / 1000, 1),
        "activity_ids": sorted(act_ids.get(shoe.id, []), reverse=True),
        "first_used": first_day[shoe.id].isoformat() if shoe.id in first_day else None,
        "years": sorted({d.year for d in per_day_m[shoe.id]}) if shoe.id in per_day_m else [],
        "is_default": shoe.id == default_id,
    } for shoe in shoes]

    _write_json(static_dir / "shoes.json", shoes_meta)
    _write_json(static_dir / "shoes_timeline.json", daily)


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
    (static_dir / ".schema_version").write_text(STATIC_SCHEMA_VERSION)


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
            (static_dir / (name + ".br")).unlink(missing_ok=True)
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
