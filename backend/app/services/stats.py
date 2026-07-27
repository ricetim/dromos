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
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.config import DISPLAY_TZ
from app.models import Activity, DataPoint, UserProfile
from app.services.analytics import (
    compute_vdot,
    compute_vdot_hr_adjusted,
    compute_pace_zones,
    compute_hrtss,
    compute_training_loads,
    predict_race_time_s,
)

_DISPLAY_TZ = ZoneInfo(DISPLAY_TZ)


def _local_date(dt: datetime) -> date:
    """Calendar day of a stored timestamp in the configured display zone.

    Activity timestamps are naive UTC (see models.py); assume UTC when no
    tzinfo is present, then convert so the day flips at local midnight.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_DISPLAY_TZ).date()


# ---------------------------------------------------------------------------
# Training load (ATL / CTL / TSB)
# ---------------------------------------------------------------------------

def _build_tss_by_date(session: Session) -> dict[date, float]:
    """Compute daily hrTSS for all activities using stored DataPoints."""
    profile = session.get(UserProfile, 1) or UserProfile()
    acts = session.exec(select(Activity).order_by(Activity.started_at)).all()
    tss_by_date: dict[date, float] = {}

    for act in acts:
        day = _local_date(act.started_at)
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
    today = datetime.now(_DISPLAY_TZ).date()
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

def _extract_series(dps) -> tuple[list[float], list[float]]:
    """Split datapoints into parallel (distance_m, epoch_seconds) float lists.

    Built once per activity and reused across every target distance. The float
    seconds matter: the sliding window below runs tens of millions of
    iterations, and datetime subtraction there costs far more than a plain
    float subtract.
    """
    dist: list[float] = []
    tsec: list[float] = []
    for dp in dps:
        if dp.distance_m is not None and dp.timestamp is not None:
            dist.append(dp.distance_m)
            tsec.append(dp.timestamp.timestamp())
    return dist, tsec


def _fastest_segment(dist: list[float], tsec: list[float], target_m: float,
                     gps_correction: float = 0.0):
    """
    Fastest segment of at least target_m * (1 - gps_correction) meters.

    GPS tracks typically under-report distance by 1-3%, so we require only
    98% of the nominal target distance to avoid false negatives. There is no
    upper-bound cap — a slightly-long segment is fine; a short one is not.

    For each right pointer, advance left as far right as possible while the
    span stays >= min_span, minimising elapsed time for that window.
    Returns (time_s, start_elapsed_s, end_elapsed_s) or None.
    """
    n = len(dist)
    if n < 2:
        return None
    min_span = target_m * (1 - gps_correction)
    t0 = tsec[0]
    best = None
    left = 0
    for right in range(1, n):
        # Advance left as far right as possible while span stays >= min_span
        while left + 1 < right and dist[right] - dist[left + 1] >= min_span:
            left += 1
        if dist[right] - dist[left] >= min_span:
            t = tsec[right] - tsec[left]
            if t > 0 and (best is None or t < best[0]):
                best = (t, tsec[left] - t0, tsec[right] - t0)
    return best


def _find_fastest_segment(dps, target_m: float, gps_correction: float = 0.0):
    """Convenience wrapper taking raw datapoints. Prefer the split
    _extract_series/_fastest_segment pair when scanning several distances over
    the same activity, so the series is built once instead of per distance."""
    dist, tsec = _extract_series(dps)
    return _fastest_segment(dist, tsec, target_m, gps_correction)


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


def refresh_pb_cache(session: Session) -> int:
    """Compute and store ActivityPB rows for activities not yet processed.

    An activity's DataPoints are immutable after import, so its fastest segment
    per distance is computed exactly once. Returns the number of activities
    processed (0 on the common path, where nothing new has been imported).
    """
    from app.models import ActivityPB

    pending = session.exec(
        select(Activity.id, Activity.distance_m).where(Activity.pb_cached == False)  # noqa: E712
    ).all()
    if not pending:
        return 0
    pending_dist = {aid: dist or 0.0 for aid, dist in pending}

    # Only the new activities' points — not the whole table.
    rows = session.exec(
        select(DataPoint.activity_id, DataPoint.distance_m, DataPoint.timestamp)
        .where(DataPoint.activity_id.in_(list(pending_dist)))
        .where(DataPoint.distance_m.is_not(None))
        .order_by(DataPoint.activity_id, DataPoint.timestamp)
    ).all()

    dps_by_act: dict[int, list] = {}
    for act_id, dist_m, ts in rows:
        dps_by_act.setdefault(act_id, []).append(_DpRow(dist_m, ts))

    for act_id, total_dist in pending_dist.items():
        dps = dps_by_act.get(act_id, ())
        if len(dps) >= 2:
            dist, tsec = _extract_series(dps)
            for label, target_m in _PB_DISTANCES:
                if total_dist < target_m:
                    continue
                found = _fastest_segment(dist, tsec, target_m)
                if found is None:
                    continue
                time_s, t_start, t_end = found
                session.add(ActivityPB(
                    activity_id=act_id, label=label, time_s=time_s,
                    start_elapsed_s=t_start, end_elapsed_s=t_end,
                ))
        # Mark processed even when nothing qualified, so short activities
        # aren't rescanned on every rebuild.
        act = session.get(Activity, act_id)
        if act:
            act.pb_cached = True
            session.add(act)

    session.commit()
    return len(pending_dist)


def get_personal_bests(session: Session) -> dict:
    """
    Fastest real segments for common distances (400 m → marathon).

    Reads the per-activity ActivityPB cache, computing only what is missing,
    then merges the global top N per distance.
    """
    from app.models import ActivityPB

    refresh_pb_cache(session)

    _TOP_N = 20
    bests: dict[str, list] = {label: [] for label, _ in _PB_DISTANCES}
    for label, time_s, act_id, t_start, t_end in session.exec(
        select(ActivityPB.label, ActivityPB.time_s, ActivityPB.activity_id,
               ActivityPB.start_elapsed_s, ActivityPB.end_elapsed_s)
        .order_by(ActivityPB.label, ActivityPB.time_s)
    ).all():
        bucket = bests.get(label)
        # Rows arrive fastest-first per label, so the first _TOP_N are the best.
        if bucket is not None and len(bucket) < _TOP_N:
            bucket.append((time_s, act_id, t_start, t_end))

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
