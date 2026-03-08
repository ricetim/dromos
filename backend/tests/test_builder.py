import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models import Activity, DataPoint, Goal, Shoe, TrainingPlan
from app.services.builder import rebuild_activity, rebuild_globals, rebuild_all, _tile_xy
from app.services.builder import _compute_eddington, _compute_yearly


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


def test_eddington_simple():
    # 5 days each >= 5 miles -> E=5; only 4 days >= 6 miles -> E=5 still
    daily_miles = {
        "2024-01-01": 5.1,
        "2024-01-02": 5.5,
        "2024-01-03": 6.0,
        "2024-01-04": 6.2,
        "2024-01-05": 5.0,
    }
    result = _compute_eddington(daily_miles)
    assert result["current_e"] == 5
    assert isinstance(result["next_e_gap"], int)
    assert result["next_e_gap"] == 1  # need 1 more day >= 6 miles


def test_eddington_zero_when_no_data():
    result = _compute_eddington({})
    assert result["current_e"] == 0
    assert result["next_e_gap"] == 1


def test_eddington_history_grows():
    daily_miles = {f"2024-01-{i:02d}": float(i) for i in range(1, 10)}
    result = _compute_eddington(daily_miles)
    history = result["history"]
    assert len(history) > 0
    assert history[-1]["e"] == result["current_e"]


def test_yearly_groups_by_week():
    acts = [
        {"started_at": "2024-01-08T08:00:00", "distance_m": 10000},
        {"started_at": "2023-01-09T08:00:00", "distance_m": 8000},
    ]
    result = _compute_yearly(acts)
    assert "2024" in result["years"]
    assert "2023" in result["years"]


def test_rebuild_all(session, act, tmp_path):
    rebuild_all(session, static_dir=tmp_path, tile_dir=tmp_path / "tiles")

    assert (tmp_path / "activities.json").exists()
    assert (tmp_path / f"activity-{act.id}.json").exists()
    assert (tmp_path / f"datapoints-{act.id}.json").exists()
    assert (tmp_path / "dashboard.json").exists()


def test_bg_rebuild_after_activity_update_rewrites_files(session, act, tmp_path, monkeypatch):
    from app.services import builder
    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        yield session

    monkeypatch.setattr(builder, "_new_session", _fake_session)

    # Update the activity
    act.notes = "felt great"
    session.add(act)
    session.commit()

    builder.bg_rebuild_after_activity_update(act.id, static_dir=tmp_path)

    assert (tmp_path / f"activity-{act.id}.json").exists()
    assert (tmp_path / "activities.json").exists()
    data = json.loads((tmp_path / f"activity-{act.id}.json").read_text())
    assert data["activity"]["notes"] == "felt great"


def test_bg_rebuild_after_delete_removes_files(session, act, tmp_path, monkeypatch):
    """Verify bg_rebuild_after_delete deletes per-activity files."""
    from contextlib import contextmanager
    from app.services import builder

    # Create the activity files
    rebuild_activity(act.id, session, static_dir=tmp_path)
    assert (tmp_path / f"activity-{act.id}.json").exists()
    assert (tmp_path / f"datapoints-{act.id}.json").exists()

    # Monkeypatch _new_session to return the test session as a context manager
    @contextmanager
    def _fake_session():
        yield session

    monkeypatch.setattr(builder, "_new_session", _fake_session)

    # Delete the activity from DB first
    from app.models import DataPoint
    from sqlmodel import select as sq_select
    for dp in session.exec(sq_select(DataPoint).where(DataPoint.activity_id == act.id)).all():
        session.delete(dp)
    session.delete(act)
    session.commit()

    # Call bg_rebuild_after_delete with our tmp_path
    builder.bg_rebuild_after_delete(act.id, static_dir=tmp_path)

    # Per-activity files should be gone
    assert not (tmp_path / f"activity-{act.id}.json").exists()
    assert not (tmp_path / f"datapoints-{act.id}.json").exists()
    # Global files should be rebuilt
    assert (tmp_path / "activities.json").exists()
    acts = json.loads((tmp_path / "activities.json").read_text())
    assert acts == []
