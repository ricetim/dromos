"""Tests for the derived-data caches added to avoid rescanning DataPoints on
every snapshot rebuild: Activity.thumb_track and the ActivityPB table.

The risk these cover is staleness — a cache that never invalidates would keep a
deleted run on the personal-best leaderboard, or serve a thumbnail for a route
that no longer exists.
"""
import json
import math
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.models import Activity, ActivityPB, DataPoint
from app.services.builder import (
    _THUMB_MAX_POINTS, _rebuild_activities, _simplify, _thumb_track,
    rebuild_activity,
)
from app.services.stats import get_personal_bests, refresh_pb_cache


def _make_activity(session, *, distance_m=6000.0, minutes=30, start_lat=37.0):
    """An activity with a 1-point-per-minute stream covering distance_m."""
    a = Activity(
        source="manual_upload",
        started_at=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
        distance_m=distance_m,
        duration_s=minutes * 60,
        sport_type="run",
    )
    session.add(a)
    session.flush()
    t0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    for i in range(minutes + 1):
        session.add(DataPoint(
            activity_id=a.id,
            timestamp=t0 + timedelta(minutes=i),
            lat=start_lat + i * 0.001,
            lon=-122.0 + i * 0.001,
            distance_m=distance_m * i / minutes,
            speed_m_s=distance_m / (minutes * 60),
        ))
    session.commit()
    session.refresh(a)
    return a


# ── ActivityPB cache ─────────────────────────────────────────────────────────

def test_pb_cache_populates_and_marks_activity(session):
    act = _make_activity(session)
    assert act.pb_cached is False

    n = refresh_pb_cache(session)
    assert n == 1
    session.refresh(act)
    assert act.pb_cached is True

    rows = session.exec(select(ActivityPB).where(ActivityPB.activity_id == act.id)).all()
    assert rows, "expected cached PB rows for a 6 km activity"
    # 6 km activity: distances up to 5k qualify, 8k and beyond do not.
    labels = {r.label for r in rows}
    assert "5k" in labels
    assert "10k" not in labels


def test_pb_cache_is_not_recomputed_on_second_call(session):
    _make_activity(session)
    assert refresh_pb_cache(session) == 1
    # Nothing new imported — the expensive path must not run again.
    assert refresh_pb_cache(session) == 0


def test_pb_cache_marks_short_activity_so_it_is_not_rescanned(session):
    """An activity too short for any PB distance yields no rows, but must still
    be flagged — otherwise it is rescanned on every single rebuild."""
    act = _make_activity(session, distance_m=200.0, minutes=2)
    refresh_pb_cache(session)
    session.refresh(act)
    assert act.pb_cached is True
    assert session.exec(
        select(ActivityPB).where(ActivityPB.activity_id == act.id)
    ).all() == []
    assert refresh_pb_cache(session) == 0


def test_new_activity_is_picked_up_after_cache_exists(session):
    _make_activity(session)
    get_personal_bests(session)

    second = _make_activity(session, distance_m=7000.0, start_lat=38.0)
    pbs = get_personal_bests(session)
    ids = {e["activity_id"] for e in pbs["5k"]}
    assert second.id in ids, "a newly imported activity must reach the leaderboard"


def test_deleting_activity_removes_it_from_personal_bests(session, client):
    act = _make_activity(session)
    pbs = get_personal_bests(session)
    assert act.id in {e["activity_id"] for e in pbs["5k"]}

    resp = client.delete(f"/api/activities/{act.id}")
    assert resp.status_code in (200, 204), resp.text

    assert session.exec(
        select(ActivityPB).where(ActivityPB.activity_id == act.id)
    ).all() == [], "cached PB rows outlived the activity"
    assert get_personal_bests(session)["5k"] is None


def test_cached_and_uncached_personal_bests_agree(session):
    """The cache must not change results — only how fast they are produced."""
    _make_activity(session)
    _make_activity(session, distance_m=9000.0, minutes=45, start_lat=39.0)

    first = get_personal_bests(session)      # cold: computes and stores
    second = get_personal_bests(session)     # warm: served from cache
    assert first == second


# ── Activity.thumb_track cache ───────────────────────────────────────────────

def test_rebuild_activity_caches_thumb_track(session, tmp_path):
    act = _make_activity(session)
    assert act.thumb_track is None

    rebuild_activity(act.id, session, static_dir=tmp_path)

    session.refresh(act)
    assert act.thumb_track is not None
    points = json.loads(act.thumb_track)
    assert len(points) >= 2
    assert all(len(p) == 2 for p in points), "thumbnail points are [lat, lon]"


def test_rebuild_activities_backfills_missing_thumb_track(session, tmp_path):
    """Activities imported before the cache existed have thumb_track NULL; the
    first globals rebuild must backfill them rather than emit an empty route."""
    act = _make_activity(session)
    assert act.thumb_track is None

    _rebuild_activities(session, tmp_path)

    acts = json.loads((tmp_path / "activities.json").read_text())
    assert len(acts[0]["track"]) >= 2, "backfilled thumbnail should have points"

    session.refresh(act)
    assert act.thumb_track is not None, "backfill must persist so it runs once"


def test_rebuild_activities_uses_cached_thumb_track(session, tmp_path):
    """With the column populated, activities.json is built from it — proven by
    writing a sentinel the DataPoints could never produce."""
    act = _make_activity(session)
    act.thumb_track = json.dumps([[1.0, 2.0], [3.0, 4.0]])
    session.add(act)
    session.commit()

    _rebuild_activities(session, tmp_path)

    acts = json.loads((tmp_path / "activities.json").read_text())
    assert acts[0]["track"] == [[1.0, 2.0], [3.0, 4.0]]


def test_thumb_track_coordinates_are_rounded(session, tmp_path):
    act = _make_activity(session)
    rebuild_activity(act.id, session, static_dir=tmp_path)
    session.refresh(act)
    for lat, lon in json.loads(act.thumb_track):
        assert lat == round(lat, 5)
        assert lon == round(lon, 5)


# ── thumbnail simplification ─────────────────────────────────────────────────

def test_simplify_drops_collinear_points_but_keeps_corners():
    """A straight run of points collapses to its endpoints; a corner survives."""
    straight = [(0.0, i * 0.001) for i in range(20)]
    assert _simplify(straight, 1e-6) == [straight[0], straight[-1]]

    corner = [(0.0, 0.0), (0.0, 0.005), (0.0, 0.01), (0.005, 0.01), (0.01, 0.01)]
    out = _simplify(corner, 1e-4)
    assert (0.0, 0.01) in out, "the turn itself must be kept"
    assert len(out) == 3


def test_simplify_keeps_endpoints_and_order():
    pts = [(0.0, 0.0), (0.001, 0.004), (0.002, 0.0), (0.003, 0.004), (0.004, 0.0)]
    out = _simplify(pts, 1e-5)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    assert out == [p for p in pts if p in out], "original ordering preserved"


def test_simplify_handles_degenerate_input():
    assert _simplify([], 0.1) == []
    assert _simplify([(1.0, 2.0)], 0.1) == [(1.0, 2.0)]
    # A closed loop gives a zero-length chord — must not divide by zero.
    loop = [(0.0, 0.0), (0.01, 0.01), (0.0, 0.0)]
    assert len(_simplify(loop, 1e-6)) == 3


def test_thumb_track_respects_the_point_cap():
    """A jagged track that resists simplification is still capped."""
    zigzag = [(i * 0.0001, (i % 2) * 0.01) for i in range(2000)]
    assert len(_thumb_track(zigzag)) <= _THUMB_MAX_POINTS


def test_thumb_track_fidelity_is_scale_invariant():
    """The same route shape, large or small, keeps a similar number of points —
    epsilon is relative to the bounding box, not an absolute distance."""
    shape = [(math.sin(i / 12) * 0.02, i * 0.0005) for i in range(400)]
    big = _thumb_track(shape)
    small = _thumb_track([(lat / 20, lon / 20) for lat, lon in shape])
    assert abs(len(big) - len(small)) <= 2
