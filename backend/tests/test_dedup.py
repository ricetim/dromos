"""Unit tests for the pure Strava/local de-duplication matchers."""
from app.services.dedup import (
    LocalCandidate,
    distance_within,
    best_fallback_match,
    closest_in_window,
    FALLBACK_WINDOW_S,
)

BASE = 1_700_000_000  # arbitrary unix seconds


def test_distance_within_absolute_floor():
    # For short runs the 150 m floor dominates (5% of 1 km is only 50 m)
    assert distance_within(1000, 1100)
    assert distance_within(1000, 1150)
    assert not distance_within(1000, 1200)


def test_distance_within_percentage():
    # 5% of 20 km = 1 km tolerance
    assert distance_within(20000, 20900)
    assert not distance_within(20000, 21200)


def test_fallback_matches_drifted_start_same_distance():
    # The duplicate bug: Coros and Strava twin recorded 4 min apart (well past
    # the 180 s primary window) but with identical distance — must still match.
    cands = [LocalCandidate(id=1, start_ts=BASE, distance_m=10000)]
    match, dt = best_fallback_match(BASE + 240, 10000, cands)
    assert match is not None and match.id == 1 and dt == 240


def test_fallback_rejects_distance_mismatch():
    # Close in time but clearly a different run — must NOT merge.
    cands = [LocalCandidate(id=1, start_ts=BASE, distance_m=10000)]
    match, _ = best_fallback_match(BASE + 60, 5000, cands)
    assert match is None


def test_fallback_rejects_outside_window():
    cands = [LocalCandidate(id=1, start_ts=BASE, distance_m=10000)]
    match, _ = best_fallback_match(BASE + FALLBACK_WINDOW_S + 1, 10000, cands)
    assert match is None


def test_fallback_picks_closest_in_time():
    cands = [
        LocalCandidate(id=1, start_ts=BASE + 600, distance_m=10000),
        LocalCandidate(id=2, start_ts=BASE + 120, distance_m=10000),
    ]
    match, dt = best_fallback_match(BASE, 10000, cands)
    assert match.id == 2 and dt == 120


def test_closest_in_window_ignores_distance():
    cands = [LocalCandidate(id=1, start_ts=BASE + 90, distance_m=99999)]
    near, dt = closest_in_window(BASE, cands)
    assert near.id == 1 and dt == 90


def test_closest_in_window_none_when_far():
    cands = [LocalCandidate(id=1, start_ts=BASE + FALLBACK_WINDOW_S + 5, distance_m=10000)]
    near, _ = closest_in_window(BASE, cands)
    assert near is None
