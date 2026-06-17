"""Pure matching helpers for de-duplicating Strava activities against the
local set (which is largely populated from Coros).

The same physical run can land in both Coros and Strava with start times that
differ by more than a minute (GPS-acquisition time vs. the "official" start),
which is what caused a Strava copy of a Coros run to be imported as a separate
activity. Matching therefore happens in two passes:

1. **Time match** — within ``TIME_MATCH_S`` of each other (cheap, exact-ish).
2. **Distance fallback** — within a much wider ``FALLBACK_WINDOW_S`` *and* with
   distances within tolerance. This catches drifted start times without
   falsely merging two genuinely different runs (you don't run twice within
   20 minutes), because it also requires the distances to agree.

These functions are intentionally pure (no DB, no network) so they can be unit
tested directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

# Primary time-match tolerance (seconds). Widened from the original 60 s.
TIME_MATCH_S = 180
# Wider window for the distance-based fallback (seconds).
FALLBACK_WINDOW_S = 20 * 60
# Distance must agree within max(DIST_MIN_M, DIST_FRAC * larger distance).
DIST_FRAC = 0.05
DIST_MIN_M = 150.0


@dataclass
class LocalCandidate:
    """A local activity that has no strava_id yet."""
    id: int
    start_ts: int       # unix seconds (UTC)
    distance_m: float


def distance_within(a_m: float, b_m: float) -> bool:
    tol = max(DIST_MIN_M, DIST_FRAC * max(a_m, b_m))
    return abs(a_m - b_m) <= tol


def best_fallback_match(
    strava_ts: int,
    strava_dist_m: float,
    candidates: Iterable[LocalCandidate],
) -> Tuple[Optional[LocalCandidate], Optional[int]]:
    """Return ``(candidate, delta_seconds)`` for the local activity that best
    matches a Strava activity by the distance-fallback rule, or ``(None, None)``.

    Among candidates within ``FALLBACK_WINDOW_S`` whose distance is within
    tolerance, the one closest in time wins.
    """
    best: Optional[LocalCandidate] = None
    best_dt: Optional[int] = None
    for c in candidates:
        dt = abs(c.start_ts - strava_ts)
        if dt > FALLBACK_WINDOW_S:
            continue
        if not distance_within(c.distance_m, strava_dist_m):
            continue
        if best is None or dt < best_dt:
            best, best_dt = c, dt
    return best, best_dt


def closest_in_window(
    strava_ts: int,
    candidates: Iterable[LocalCandidate],
    window_s: int = FALLBACK_WINDOW_S,
) -> Tuple[Optional[LocalCandidate], Optional[int]]:
    """Closest local activity by time within ``window_s`` *regardless* of
    distance. Used only to describe near-misses in the logs."""
    best: Optional[LocalCandidate] = None
    best_dt: Optional[int] = None
    for c in candidates:
        dt = abs(c.start_ts - strava_ts)
        if dt > window_s:
            continue
        if best is None or dt < best_dt:
            best, best_dt = c, dt
    return best, best_dt
