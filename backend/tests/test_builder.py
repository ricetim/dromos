import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models import Activity, DataPoint, Goal, Shoe
from app.services.builder import rebuild_activity, rebuild_globals, rebuild_all
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

    for filename in ["activities.json", "dashboard.json", "goals.json", "shoes.json"]:
        assert (tmp_path / filename).exists(), f"{filename} not found"

    acts = json.loads((tmp_path / "activities.json").read_text())
    assert len(acts) == 1
    assert acts[0]["id"] == act.id
    assert "track" in acts[0]

    dash = json.loads((tmp_path / "dashboard.json").read_text())
    assert "summary" in dash
    assert "last_7_days" in dash["summary"]
    assert "volume" in dash
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
    assert result["next_e_gap"] == 4  # need 4 more days >= 6 miles (have 2: 6.0 and 6.2; need 6)


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
    rebuild_all(session, static_dir=tmp_path)

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


def test_rebuild_shoes_emits_day_aligned_timeline(session, tmp_path):
    """shoes.json keeps array shape with per-shoe metadata;
    shoes_timeline.json is a dense day-aligned series from first use to today,
    with carry-forward across rest days."""
    from app.services.builder import _rebuild_shoes
    from app.models import ActivityShoe

    shoe = Shoe(name="Endorphin", retirement_threshold_km=800.0)
    session.add(shoe)
    session.flush()

    a2 = Activity(
        source="manual_upload",
        started_at=datetime(2025, 6, 10, tzinfo=timezone.utc),
        distance_m=8000.0, duration_s=2400, elevation_gain_m=50.0, sport_type="run",
    )
    a1 = Activity(
        source="manual_upload",
        started_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
        distance_m=5000.0, duration_s=1800, elevation_gain_m=20.0, sport_type="run",
    )
    session.add_all([a1, a2])
    session.flush()
    session.add_all([
        ActivityShoe(activity_id=a1.id, shoe_id=shoe.id),
        ActivityShoe(activity_id=a2.id, shoe_id=shoe.id),
    ])
    session.commit()

    _rebuild_shoes(session, tmp_path)
    shoes_data = json.loads((tmp_path / "shoes.json").read_text())
    daily = json.loads((tmp_path / "shoes_timeline.json").read_text())

    assert len(shoes_data) == 1
    s = shoes_data[0]
    assert s["total_distance_km"] == 13.0
    assert s["first_used"] == "2025-01-05"
    assert s["years"] == [2025]

    key = str(shoe.id)
    by_date = {row["date"]: row for row in daily}
    assert daily[0]["date"] == "2025-01-05"
    assert by_date["2025-01-05"][key] == 5.0
    # Carry-forward across rest days
    assert by_date["2025-06-09"][key] == 5.0
    assert by_date["2025-06-10"][key] == 13.0
    # Carry-forward after last activity
    assert by_date["2025-12-31"][key] == 13.0


def test_rebuild_shoes_empty_when_no_activities(session, tmp_path):
    """A shoe with no activities is present in shoes.json but contributes no
    timeline entries; first_used is null."""
    from app.services.builder import _rebuild_shoes
    session.add(Shoe(name="Unused", retirement_threshold_km=800.0))
    session.commit()

    _rebuild_shoes(session, tmp_path)
    shoes_data = json.loads((tmp_path / "shoes.json").read_text())
    daily = json.loads((tmp_path / "shoes_timeline.json").read_text())
    assert daily == []
    s = shoes_data[0]
    assert s["total_distance_km"] == 0.0
    assert s["first_used"] is None
    assert s["years"] == []


def test_rebuild_shoes_same_day_aggregates(session, tmp_path):
    """Two activities on the same day collapse to one timeline row with
    summed cumulative km."""
    from app.services.builder import _rebuild_shoes
    from app.models import ActivityShoe

    shoe = Shoe(name="Multi", retirement_threshold_km=800.0)
    session.add(shoe)
    session.flush()
    for year, dist in [(2024, 4000.0), (2024, 3000.0), (2025, 2000.0), (2026, 1000.0)]:
        a = Activity(
            source="manual_upload",
            started_at=datetime(year, 3, 1, tzinfo=timezone.utc),
            distance_m=dist, duration_s=1800, elevation_gain_m=10.0, sport_type="run",
        )
        session.add(a)
        session.flush()
        session.add(ActivityShoe(activity_id=a.id, shoe_id=shoe.id))
    session.commit()

    _rebuild_shoes(session, tmp_path)
    shoes_data = json.loads((tmp_path / "shoes.json").read_text())
    daily = json.loads((tmp_path / "shoes_timeline.json").read_text())
    s = shoes_data[0]
    assert s["years"] == [2024, 2025, 2026]
    assert s["total_distance_km"] == 10.0

    key = str(shoe.id)
    by_date = {row["date"]: row for row in daily}
    # Same-day aggregation: 4 + 3 = 7 on 2024-03-01
    assert by_date["2024-03-01"][key] == 7.0
    assert by_date["2025-03-01"][key] == 9.0
    assert by_date["2026-03-01"][key] == 10.0


def test_rebuild_shoes_retired_line_ends_at_last_activity(session, tmp_path):
    """A retired shoe's daily series emits its final value on its last
    activity date and null thereafter — so the chart line terminates at
    retirement instead of carrying flat to today."""
    from app.services.builder import _rebuild_shoes
    from app.models import ActivityShoe

    retired_shoe = Shoe(name="Old", retirement_threshold_km=800.0, retired=True)
    active_shoe = Shoe(name="Current", retirement_threshold_km=800.0, retired=False)
    session.add_all([retired_shoe, active_shoe])
    session.flush()

    # Both shoes have an early activity on 2025-01-01 (sets axis start);
    # retired shoe last used 2025-02-01; active shoe still running on 2025-04-01.
    a1 = Activity(
        source="manual_upload",
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        distance_m=5000.0, duration_s=1500, elevation_gain_m=10.0, sport_type="run",
    )
    a2 = Activity(
        source="manual_upload",
        started_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        distance_m=4000.0, duration_s=1200, elevation_gain_m=10.0, sport_type="run",
    )
    a3 = Activity(
        source="manual_upload",
        started_at=datetime(2025, 4, 1, tzinfo=timezone.utc),
        distance_m=3000.0, duration_s=900, elevation_gain_m=10.0, sport_type="run",
    )
    session.add_all([a1, a2, a3])
    session.flush()
    session.add_all([
        ActivityShoe(activity_id=a1.id, shoe_id=retired_shoe.id),
        ActivityShoe(activity_id=a2.id, shoe_id=retired_shoe.id),
        ActivityShoe(activity_id=a3.id, shoe_id=active_shoe.id),
    ])
    session.commit()

    _rebuild_shoes(session, tmp_path)
    daily = json.loads((tmp_path / "shoes_timeline.json").read_text())
    by_date = {row["date"]: row for row in daily}
    retired_k = str(retired_shoe.id)
    active_k = str(active_shoe.id)

    # Retired shoe: real values on/before its last activity day
    assert by_date["2025-01-01"][retired_k] == 5.0
    assert by_date["2025-01-15"][retired_k] == 5.0  # rest-day carry-forward
    assert by_date["2025-02-01"][retired_k] == 9.0  # last activity day
    # Retired shoe: null after its last activity day
    assert by_date["2025-02-02"][retired_k] is None
    assert by_date["2025-04-01"][retired_k] is None
    # Active shoe is unaffected: still has its flat-tail carry-forward
    # (still active, so carries through to last row of daily)
    assert by_date["2025-04-01"][active_k] == 3.0


def test_rebuild_shoes_pre_first_use_is_null(session, tmp_path):
    """A shoe whose first use is later than another shoe's has null values
    for every day before its own first use — so the chart line starts at its
    own first activity, not the axis origin."""
    from app.services.builder import _rebuild_shoes
    from app.models import ActivityShoe

    early = Shoe(name="Early", retirement_threshold_km=800.0)
    late = Shoe(name="Late", retirement_threshold_km=800.0)
    session.add_all([early, late])
    session.flush()

    a_early = Activity(
        source="manual_upload",
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        distance_m=4000.0, duration_s=1200, elevation_gain_m=10.0, sport_type="run",
    )
    a_late = Activity(
        source="manual_upload",
        started_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        distance_m=2000.0, duration_s=600, elevation_gain_m=5.0, sport_type="run",
    )
    session.add_all([a_early, a_late])
    session.flush()
    session.add_all([
        ActivityShoe(activity_id=a_early.id, shoe_id=early.id),
        ActivityShoe(activity_id=a_late.id, shoe_id=late.id),
    ])
    session.commit()

    _rebuild_shoes(session, tmp_path)
    daily = json.loads((tmp_path / "shoes_timeline.json").read_text())
    by_date = {row["date"]: row for row in daily}
    early_k, late_k = str(early.id), str(late.id)

    assert by_date["2025-01-01"][early_k] == 4.0
    assert by_date["2025-01-01"][late_k] is None
    assert by_date["2025-02-28"][late_k] is None
    assert by_date["2025-03-01"][late_k] == 2.0
    # Early still carrying forward on Late's start day
    assert by_date["2025-03-01"][early_k] == 4.0


# ──────────────────────────────────────────────────────────────────────────
# Period volume bucketing
# ──────────────────────────────────────────────────────────────────────────

from datetime import date as _date, timedelta
from app.services.builder import _bucket_by_day, _bucket_by_week_sun_start, _compute_period_data


def _make_act(session, started_at_date, distance_m=5000.0):
    """Helper: create a minimal Activity on a given date."""
    a = Activity(
        source="manual_upload",
        started_at=datetime(started_at_date.year, started_at_date.month, started_at_date.day,
                            12, 0, tzinfo=timezone.utc),
        distance_m=distance_m,
        duration_s=1800,
        elevation_gain_m=10.0,
        sport_type="run",
    )
    session.add(a)
    session.commit()
    return a


def test_bucket_by_day_last_7_days_uses_weekday_labels(session):
    """7-day view: 7 daily buckets labeled Sun..Sat in chronological order."""
    today = _date(2026, 5, 20)  # Wednesday
    start = today - timedelta(days=6)  # Thursday May 14
    end = today

    _make_act(session, _date(2026, 5, 16))  # 5km Saturday
    from sqlmodel import select
    acts = session.exec(select(Activity)).all()

    buckets = _bucket_by_day(acts, start, end, label_style="weekday")

    assert len(buckets) == 7
    assert buckets[0] == {"date": "2026-05-14", "label": "Thu", "km": 0.0}
    assert buckets[1] == {"date": "2026-05-15", "label": "Fri", "km": 0.0}
    assert buckets[2] == {"date": "2026-05-16", "label": "Sat", "km": 5.0}
    assert buckets[6] == {"date": "2026-05-20", "label": "Wed", "km": 0.0}


def test_bucket_by_day_month_uses_day_of_month_labels(session):
    """Month view: bucket labels are day-of-month strings ('1'..'31')."""
    start = _date(2026, 5, 1)
    end = _date(2026, 5, 31)

    _make_act(session, _date(2026, 5, 10), distance_m=3000.0)
    _make_act(session, _date(2026, 5, 10), distance_m=2000.0)
    from sqlmodel import select
    acts = session.exec(select(Activity)).all()

    buckets = _bucket_by_day(acts, start, end, label_style="day_of_month")

    assert len(buckets) == 31
    assert buckets[0] == {"date": "2026-05-01", "label": "1", "km": 0.0}
    assert buckets[9] == {"date": "2026-05-10", "label": "10", "km": 5.0}
    assert buckets[30] == {"date": "2026-05-31", "label": "31", "km": 0.0}


def test_bucket_by_week_sun_start_2026(session):
    """
    Year 2026 starts on Thursday Jan 1.
    First weekly bucket date is Sun Dec 28, 2025 (Sunday on or before Jan 1).
    Label is "Jan 1" (first in-year date in that week).
    Only mileage from Jan 1 onward counts (Dec 28-31 runs are ignored).
    """
    start = _date(2026, 1, 1)
    end = _date(2026, 12, 31)

    _make_act(session, _date(2025, 12, 29), distance_m=10000.0)  # OUT of year
    _make_act(session, _date(2026, 1, 2), distance_m=8000.0)     # IN first week
    _make_act(session, _date(2026, 1, 11), distance_m=6000.0)    # IN second week (Sun)
    from sqlmodel import select
    acts = session.exec(select(Activity)).all()

    buckets = _bucket_by_week_sun_start(acts, start, end)

    assert len(buckets) == 53
    assert buckets[0]["date"] == "2025-12-28"
    assert buckets[0]["label"] == "Jan 1"
    assert buckets[0]["km"] == 8.0
    assert buckets[1]["date"] == "2026-01-04"
    assert buckets[1]["label"] == "Jan 4"
    assert buckets[2]["date"] == "2026-01-11"
    assert buckets[2]["km"] == 6.0
    assert buckets[-1]["date"] == "2026-12-27"


def test_compute_period_data_last_7_days_sum_matches_summary(session):
    """volume[period].total_km MUST equal summary[period].total_distance_km."""
    today = _date(2026, 5, 20)
    _make_act(session, _date(2026, 5, 16), distance_m=5000.0)
    _make_act(session, _date(2026, 5, 18), distance_m=8000.0)
    _make_act(session, _date(2026, 4, 30), distance_m=99000.0)
    from sqlmodel import select
    acts = session.exec(select(Activity)).all()

    summary, volume = _compute_period_data(acts, "last_7_days", today)

    assert summary["count"] == 2
    assert summary["total_distance_km"] == 13.0
    assert volume["total_km"] == 13.0
    assert sum(b["km"] for b in volume["buckets"]) == 13.0
    assert len(volume["buckets"]) == 7


def test_compute_period_data_month_uses_calendar_boundaries(session):
    today = _date(2026, 5, 20)
    _make_act(session, _date(2026, 5, 1), distance_m=4000.0)
    _make_act(session, _date(2026, 5, 31), distance_m=10000.0)
    _make_act(session, _date(2026, 4, 30), distance_m=99000.0)
    _make_act(session, _date(2026, 6, 1), distance_m=99000.0)
    from sqlmodel import select
    acts = session.exec(select(Activity)).all()

    summary, volume = _compute_period_data(acts, "month", today)

    assert summary["count"] == 2
    assert summary["total_distance_km"] == 14.0
    assert volume["total_km"] == 14.0
    assert len(volume["buckets"]) == 31
    assert volume["buckets"][0]["km"] == 4.0
    assert volume["buckets"][30]["km"] == 10.0


def test_compute_period_data_year_53_weeks_2026(session):
    today = _date(2026, 5, 20)
    _make_act(session, _date(2026, 1, 2), distance_m=8000.0)
    _make_act(session, _date(2025, 12, 31), distance_m=99000.0)
    from sqlmodel import select
    acts = session.exec(select(Activity)).all()

    summary, volume = _compute_period_data(acts, "year", today)

    assert summary["count"] == 1
    assert summary["total_distance_km"] == 8.0
    assert volume["total_km"] == 8.0
    assert len(volume["buckets"]) == 53
    assert volume["buckets"][0]["km"] == 8.0


def test_rebuild_dashboard_writes_volume_field(session, tmp_path, monkeypatch):
    """dashboard.json must contain summary{} and volume{} for all three periods."""
    fake_today = _date(2026, 5, 20)

    import app.services.builder as builder_mod
    monkeypatch.setattr(builder_mod, "_today_fn", lambda: fake_today)

    _make_act(session, _date(2026, 5, 16), distance_m=5000.0)
    _make_act(session, _date(2026, 5, 18), distance_m=8000.0)

    builder_mod._rebuild_dashboard(session, tmp_path)

    data = json.loads((tmp_path / "dashboard.json").read_text())
    assert set(data["summary"].keys()) == {"last_7_days", "month", "year"}
    assert set(data["volume"].keys()) == {"last_7_days", "month", "year"}

    last_7 = data["volume"]["last_7_days"]
    assert last_7["total_km"] == 13.0
    assert sum(b["km"] for b in last_7["buckets"]) == 13.0
    assert data["summary"]["last_7_days"]["total_distance_km"] == last_7["total_km"]

    month = data["volume"]["month"]
    assert len(month["buckets"]) == 31
    assert month["buckets"][20]["date"] == "2026-05-21"
    assert month["buckets"][20]["km"] == 0.0

    year = data["volume"]["year"]
    assert len(year["buckets"]) == 53
