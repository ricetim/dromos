"""Tests for the persistent event log endpoints."""
from app.models import EventLog


def _seed(session):
    session.add(EventLog(level="info", category="sync.strava", message="imported strava 1"))
    session.add(EventLog(level="warning", category="sync.strava", message="near-miss"))
    session.add(EventLog(level="error", category="sync.coros", message="boom"))
    session.add(EventLog(level="info", category="delete", message="deleted activity 5"))
    session.commit()


def test_logs_json_newest_first(client, session):
    _seed(session)
    r = client.get("/api/logs")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 4
    assert rows[0]["message"] == "deleted activity 5"  # highest id => newest
    assert {"id", "ts", "level", "category", "message", "details"} <= set(rows[0])


def test_logs_level_filter_is_minimum_severity(client, session):
    _seed(session)
    msgs = [x["message"] for x in client.get("/api/logs?level=warning").json()]
    assert "near-miss" in msgs       # warning
    assert "boom" in msgs            # error (higher severity)
    assert "imported strava 1" not in msgs  # info excluded


def test_logs_category_substring_filter(client, session):
    _seed(session)
    cats = {x["category"] for x in client.get("/api/logs?category=sync").json()}
    assert cats == {"sync.strava", "sync.coros"}


def test_logs_limit(client, session):
    _seed(session)
    assert len(client.get("/api/logs?limit=2").json()) == 2


def test_logs_view_renders_html(client, session):
    _seed(session)
    r = client.get("/api/logs/view")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "system log" in r.text
    assert "near-miss" in r.text
