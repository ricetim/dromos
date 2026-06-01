"""
Aggregate running statistics computed from the database.

These functions are the source of truth for the dashboard's training-load,
VDOT, and personal-best sections. They are consumed by
``app.services.builder._rebuild_dashboard``, which bakes their output into
``dashboard.json``; the frontend then reads that static file directly (reads
never touch Python). Keep these pure: take a ``Session``, return plain data.
"""
import math
from collections import namedtuple
from datetime import date, timedelta

from sqlmodel import Session, select

from app.models import Activity, DataPoint, UserProfile
from app.services.analytics import (
    compute_vdot,
    compute_vdot_hr_adjusted,
    compute_pace_zones,
    compute_hrtss,
    compute_training_loads,
    predict_race_time_s,
)


# ---------------------------------------------------------------------------
# Training load (ATL / CTL / TSB)
# ---------------------------------------------------------------------------

def _build_tss_by_date(session: Session) -> dict[date, float]:
    """Compute daily hrTSS for all activities using stored DataPoints."""
    profile = session.get(UserProfile, 1) or UserProfile()
    acts = session.exec(select(Activity).order_by(Activity.started_at)).all()
    tss_by_date: dict[date, float] = {}

    for act in acts:
        day = act.started_at.date()
        if act.avg_hr and act.duration_s:
            # Fast path: no datapoints needed — estimate from average HR
            hr_rest, hr_max = profile.hr_rest, profile.hr_max
            hr_range = hr_max - hr_rest
            delta_hr = max(0.0, min((act.avg_hr - hr_rest) / hr_range, 1.0))
            b = 1.92
            trimp = (act.duration_s / 60.0) * delta_hr * math.exp(b * delta_hr)
        else:
            # Fallback: rough estimate from duration only (assume easy effort)
            trimp = (act.duration_s / 60.0) * 0.3 * math.exp(1.92 * 0.3)
        tss_by_date[day] = tss_by_date.get(day, 0.0) + compute_hrtss(trimp)

    return tss_by_date


def get_training_load(session: Session, days: int = 90) -> list[dict]:
    """Return daily ATL, CTL, TSB (training load) for the last `days` days."""
    tss_by_date = _build_tss_by_date(session)
    today = date.today()
    start = today - timedelta(days=days)
    loads = compute_training_loads(tss_by_date, start_date=start, end_date=today)

    return [
        {
            "date": d.isoformat(),
            "ctl": round(v.ctl, 1),
            "atl": round(v.atl, 1),
            "tsb": round(v.tsb, 1),
            "tss": round(tss_by_date.get(d, 0.0), 1),
        }
        for d, v in sorted(loads.items())
    ]


# ---------------------------------------------------------------------------
# VDOT estimate + race predictions + pace zones
# ---------------------------------------------------------------------------

def get_vdot(session: Session) -> dict:
    """
    Estimate current VDOT from recent training runs using HR-adjusted method.

    Uses Swain (1994) %VO2max = 1.0197×%HRR + 0.01 to account for the fact
    that training runs are run at sub-maximal effort. Takes the median of
    all qualifying activities in the last 90 days (requires avg_hr data).

    Falls back to the raw Daniels formula (best performance) only when no
    HR data is available — this will underestimate VDOT for easy runs.
    """
    profile = session.get(UserProfile, 1) or UserProfile()
    hr_max = profile.hr_max
    hr_rest = profile.hr_rest

    cutoff = date.today() - timedelta(days=28)
    acts = session.exec(
        select(Activity)
        .where(Activity.started_at >= cutoff.isoformat())
        .where(Activity.distance_m >= 3000)   # at least 3km for meaningful estimate
        .where(Activity.duration_s > 0)
    ).all()

    vdot_estimates = []
    for act in acts:
        if act.avg_hr and act.distance_m > 0 and act.duration_s > 0:
            try:
                v = compute_vdot_hr_adjusted(
                    act.distance_m, act.duration_s, act.avg_hr, hr_max, hr_rest
                )
                if 20 < v < 85:  # sanity range
                    vdot_estimates.append((v, act.id))
            except ValueError:
                pass

    method = "hr_adjusted"
    if vdot_estimates:
        # Use 75th percentile to reduce noise from unusually easy/hard days
        vdot_estimates.sort(key=lambda x: x[0])
        mid = int(len(vdot_estimates) * 0.75)
        mid = min(mid, len(vdot_estimates) - 1)
        best_vdot, best_act_id = vdot_estimates[mid]
    else:
        # Fallback: raw Daniels (accurate only for races/time-trials)
        method = "raw_daniels_fallback"
        best_vdot = None
        best_act_id = None
        for act in acts:
            if act.distance_m > 0 and act.duration_s > 0:
                try:
                    v = compute_vdot(act.distance_m, act.duration_s)
                    if best_vdot is None or v > best_vdot:
                        best_vdot = v
                        best_act_id = act.id
                except ValueError:
                    pass

    if best_vdot is None:
        return {"vdot": None, "based_on_activity_id": None, "method": method,
                "hr_max": hr_max, "hr_rest": hr_rest}

    zones = compute_pace_zones(best_vdot)
    predictions = {}
    for name, dist in [("5k", 5000), ("10k", 10000), ("half", 21097), ("marathon", 42195)]:
        try:
            t = predict_race_time_s(best_vdot, dist)
            predictions[name] = round(t)
        except Exception:
            predictions[name] = None

    return {
        "vdot": round(best_vdot, 1),
        "based_on_activity_id": best_act_id,
        "method": method,
        "hr_max": hr_max,
        "hr_rest": hr_rest,
        "sample_size": len(vdot_estimates),
        "race_predictions_s": predictions,
        "pace_zones_s_per_km": {
            "easy_lo": round(zones.easy_lo),
            "easy_hi": round(zones.easy_hi),
            "marathon": round(zones.marathon),
            "threshold": round(zones.threshold),
            "interval": round(zones.interval),
            "repetition": round(zones.repetition),
        },
    }


# ---------------------------------------------------------------------------
# Personal bests (fastest real segment per distance)
# ---------------------------------------------------------------------------

def _find_fastest_segment(dps, target_m: float, gps_correction: float = 0.0):
    """
    Fastest segment of at least target_m * (1 - gps_correction) meters.

    GPS tracks typically under-report distance by 1-3%, so we require only
    98% of the nominal target distance to avoid false negatives. There is no
    upper-bound cap — a slightly-long segment is fine; a short one is not.

    For each right pointer, advance left as far right as possible while the
    span stays >= min_span, minimising elapsed time for that window.
    Returns (time_s, start_elapsed_s, end_elapsed_s) or None.
    """
    min_span = target_m * (1 - gps_correction)
    pts = [(dp.distance_m, dp.timestamp) for dp in dps
           if dp.distance_m is not None and dp.timestamp is not None]
    if len(pts) < 2:
        return None
    t0 = pts[0][1]
    best = None
    left = 0
    for right in range(1, len(pts)):
        # Advance left as far right as possible while span stays >= min_span
        while left + 1 < right and pts[right][0] - pts[left + 1][0] >= min_span:
            left += 1
        span = pts[right][0] - pts[left][0]
        if span >= min_span:
            t = (pts[right][1] - pts[left][1]).total_seconds()
            if t > 0 and (best is None or t < best[0]):
                t_start = (pts[left][1] - t0).total_seconds()
                t_end = (pts[right][1] - t0).total_seconds()
                best = (t, t_start, t_end)
    return best


_PB_DISTANCES = [
    ("400m",     400.0),
    ("800m",     800.0),
    ("1k",       1000.0),
    ("1 mile",   1609.0),
    ("2 mile",   3218.0),
    ("3k",       3000.0),
    ("5k",       5000.0),
    ("8k",       8000.0),
    ("10k",      10000.0),
    ("15k",      15000.0),
    ("10 mile",  16093.0),
    ("20k",      20000.0),
    ("half",     21097.0),
    ("25k",      25000.0),
    ("30k",      30000.0),
    ("marathon", 42195.0),
]

_DpRow = namedtuple("_DpRow", ["distance_m", "timestamp"])


def get_personal_bests(session: Session) -> dict:
    """
    Fastest real segments for common distances (400 m → marathon).

    Uses a single bulk query + two-pointer sliding window.
    """
    # Activity distances to skip short activities early
    act_dist = {a[0]: a[1] for a in session.exec(
        select(Activity.id, Activity.distance_m)
    ).all()}

    # Single bulk query — only distance + timestamp columns, sorted by activity then time.
    # The (activity_id, timestamp) compound index makes this efficient.
    rows = session.exec(
        select(DataPoint.activity_id, DataPoint.distance_m, DataPoint.timestamp)
        .where(DataPoint.distance_m.is_not(None))
        .order_by(DataPoint.activity_id, DataPoint.timestamp)
    ).all()

    # Group into per-activity point lists
    dps_by_act: dict[int, list] = {}
    for act_id, dist_m, ts in rows:
        if act_id not in dps_by_act:
            dps_by_act[act_id] = []
        dps_by_act[act_id].append(_DpRow(dist_m, ts))

    _TOP_N = 20
    # bests[label] = sorted list of (time_s, act_id, t_start, t_end), ascending by time_s
    bests: dict[str, list] = {label: [] for label, _ in _PB_DISTANCES}

    for act_id, dps in dps_by_act.items():
        if len(dps) < 2:
            continue
        total_dist = act_dist.get(act_id, 0.0)
        for label, target_m in _PB_DISTANCES:
            if total_dist < target_m:
                continue
            result = _find_fastest_segment(dps, target_m)
            if result is None:
                continue
            time_s, t_start, t_end = result
            bucket = bests[label]
            # Keep only top N; discard if slower than current worst
            if len(bucket) < _TOP_N or time_s < bucket[-1][0]:
                bucket.append((time_s, act_id, t_start, t_end))
                bucket.sort(key=lambda x: x[0])
                if len(bucket) > _TOP_N:
                    bucket.pop()

    out = {}
    for label, _ in _PB_DISTANCES:
        entries = bests[label]
        out[label] = [
            {
                "rank": i + 1,
                "time_s": int(round(e[0])),
                "activity_id": e[1],
                "start_elapsed_s": e[2],
                "end_elapsed_s": e[3],
            }
            for i, e in enumerate(entries)
        ] or None

    return out
