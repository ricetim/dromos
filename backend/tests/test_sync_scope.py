"""Sync-loop behaviours that matter at a 5-minute poll cadence:
quiet no-op polls (so the capped event log keeps real history) and a bounded
Strava photo scan (so one run can't exhaust Strava's rate limit)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.models import Activity, EventLog
from app.routers import sync
from app.services import eventlog


@pytest.fixture
def sync_env(session, monkeypatch):
    monkeypatch.setattr(sync, "engine", session.get_bind())
    monkeypatch.setattr(eventlog, "engine", session.get_bind())  # log writes use their own session
    rebuilds = []
    monkeypatch.setattr(sync, "bg_rebuild_after_import", lambda ids: rebuilds.append(list(ids)))
    return rebuilds


def _logs(session, category):
    return session.exec(select(EventLog).where(EventLog.category == category)).all()


def test_noop_coros_poll_writes_no_log_rows_and_no_rebuild(session, sync_env, monkeypatch):
    session.add(Activity(source="coros", external_id="111", started_at=datetime(2026, 1, 1)))
    session.commit()
    monkeypatch.setattr(sync, "COROS_EMAIL", "x@example.com")
    monkeypatch.setattr(sync, "coros_login", lambda e, p: ("tok", "uid"))
    monkeypatch.setattr(sync, "coros_list", lambda t, u: [{"labelId": "111", "sportType": 100}])

    sync._sync_coros()

    assert _logs(session, "sync.coros") == [], "a poll that found nothing must not log"
    assert sync._last_sync["status"] == "ok" and sync._last_sync["new_activities"] == 0
    assert sync_env == [[]], "no activities to rebuild"


def test_failed_coros_poll_is_still_logged(session, sync_env, monkeypatch):
    monkeypatch.setattr(sync, "COROS_EMAIL", "x@example.com")
    def boom(e, p): raise RuntimeError("coros down")
    monkeypatch.setattr(sync, "coros_login", boom)

    sync._sync_coros()

    rows = _logs(session, "sync.coros")
    assert [r.level for r in rows] == ["error"]


def test_strava_photo_scan_limited_to_recent_and_touched(session, sync_env, monkeypatch):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old = Activity(source="coros", strava_id="1", started_at=now - timedelta(days=200))
    recent = Activity(source="coros", strava_id="2", started_at=now - timedelta(days=3))
    session.add_all([old, recent]); session.commit()

    monkeypatch.setattr(sync, "STRAVA_REFRESH_TOKEN", "rt")
    monkeypatch.setattr(sync, "get_access_token", lambda: "tok")
    # Strava lists both runs at the same start times, so both match and
    # nothing is re-linked — neither counts as "touched".
    def iso(d): return d.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(sync, "fetch_athlete_activities", lambda tok, after=0: [
        {"id": 1, "start_date": iso(old.started_at), "sport_type": "Run", "distance": 0},
        {"id": 2, "start_date": iso(recent.started_at), "sport_type": "Run", "distance": 0},
    ])
    scanned = []
    monkeypatch.setattr(sync, "sync_photos_for_activity",
                        lambda a, s, t: scanned.append(a.strava_id) or 0)

    sync._sync_strava_activities()

    assert scanned == ["2"], "only the recent activity should be scanned for photos"
