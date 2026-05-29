import pathlib
import pytest
from sqlmodel import Session, select
from app.models import UserProfile, Shoe, ActivityShoe, Activity
from app.services.shoe_default import stamp_default_shoe
from datetime import datetime

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SAMPLE_FIT = FIXTURES / "sample.fit"


def test_userprofile_has_default_shoe_id_field(session: Session):
    """UserProfile should have a nullable default_shoe_id column."""
    profile = UserProfile(id=1, default_shoe_id=None)
    session.add(profile)
    session.commit()
    refreshed = session.get(UserProfile, 1)
    assert refreshed is not None
    assert refreshed.default_shoe_id is None


def test_userprofile_can_set_default_shoe_id(session: Session):
    shoe = Shoe(name="Test Shoe")
    session.add(shoe)
    session.commit()
    session.refresh(shoe)

    profile = UserProfile(id=1, default_shoe_id=shoe.id)
    session.add(profile)
    session.commit()
    refreshed = session.get(UserProfile, 1)
    assert refreshed.default_shoe_id == shoe.id


def _make_activity(session: Session) -> Activity:
    act = Activity(
        source="test",
        started_at=datetime(2026, 5, 27, 8, 0, 0),
        distance_m=5000,
        duration_s=1500,
        elevation_gain_m=10,
        sport_type="run",
    )
    session.add(act)
    session.flush()
    return act


def test_stamp_default_shoe_no_default_no_link(session: Session):
    """When no default is set, stamp is a no-op."""
    session.add(UserProfile(id=1, default_shoe_id=None))
    act = _make_activity(session)
    stamp_default_shoe(session, act.id)
    session.commit()

    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == act.id)
    ).all()
    assert links == []


def test_stamp_default_shoe_writes_link(session: Session):
    """When a default is set, a single ActivityShoe link is written."""
    shoe = Shoe(name="Test Shoe")
    session.add(shoe)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=shoe.id))
    act = _make_activity(session)

    stamp_default_shoe(session, act.id)
    session.commit()

    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == act.id)
    ).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id


def test_patch_profile_sets_default_shoe(client, session):
    """PATCH /api/profile {default_shoe_id: N} updates the profile."""
    shoe = Shoe(name="Tracer")
    session.add(shoe)
    session.add(UserProfile(id=1))
    session.commit()
    session.refresh(shoe)

    r = client.patch("/api/profile", json={"default_shoe_id": shoe.id})
    assert r.status_code == 200
    assert r.json()["default_shoe_id"] == shoe.id


def test_patch_profile_clears_default_shoe(client, session):
    """PATCH /api/profile {default_shoe_id: null} clears the default."""
    shoe = Shoe(name="Tracer")
    session.add(shoe)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=shoe.id))
    session.commit()

    r = client.patch("/api/profile", json={"default_shoe_id": None})
    assert r.status_code == 200
    assert r.json()["default_shoe_id"] is None


def test_patch_profile_rejects_missing_shoe(client, session):
    session.add(UserProfile(id=1))
    session.commit()
    r = client.patch("/api/profile", json={"default_shoe_id": 9999})
    assert r.status_code == 400


def test_patch_profile_rejects_retired_shoe(client, session):
    shoe = Shoe(name="Old", retired=True)
    session.add(shoe)
    session.add(UserProfile(id=1))
    session.commit()
    session.refresh(shoe)
    r = client.patch("/api/profile", json={"default_shoe_id": shoe.id})
    assert r.status_code == 400


def test_retiring_default_shoe_clears_profile(client, session):
    """PATCH /api/shoes/{id} retired=True clears UserProfile.default_shoe_id."""
    shoe = Shoe(name="Speed")
    session.add(shoe)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=shoe.id))
    session.commit()
    session.refresh(shoe)

    r = client.patch(f"/api/shoes/{shoe.id}", json={"retired": True})
    assert r.status_code == 200

    profile = session.get(UserProfile, 1)
    session.refresh(profile)
    assert profile.default_shoe_id is None


def test_retiring_non_default_shoe_does_not_touch_profile(client, session):
    a = Shoe(name="A")
    b = Shoe(name="B")
    session.add(a)
    session.add(b)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=a.id))
    session.commit()
    session.refresh(a)
    session.refresh(b)

    r = client.patch(f"/api/shoes/{b.id}", json={"retired": True})
    assert r.status_code == 200

    profile = session.get(UserProfile, 1)
    session.refresh(profile)
    assert profile.default_shoe_id == a.id


def _seed_default_shoe(session) -> Shoe:
    shoe = Shoe(name="DefaultTest")
    session.add(shoe)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=shoe.id))
    session.commit()
    session.refresh(shoe)
    return shoe


@pytest.mark.skipif(not SAMPLE_FIT.exists(), reason="sample.fit fixture required")
def test_upload_stamps_default_shoe(client, session):
    shoe = _seed_default_shoe(session)

    with SAMPLE_FIT.open("rb") as f:
        r = client.post(
            "/api/activities/upload",
            files={"file": ("sample.fit", f, "application/octet-stream")},
        )
    assert r.status_code == 201
    act_id = r.json()["id"]

    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == act_id)
    ).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id


@pytest.mark.skipif(not SAMPLE_FIT.exists(), reason="sample.fit fixture required")
def test_upload_without_default_creates_no_link(client, session):
    session.add(UserProfile(id=1, default_shoe_id=None))
    session.commit()

    with SAMPLE_FIT.open("rb") as f:
        r = client.post(
            "/api/activities/upload",
            files={"file": ("sample.fit", f, "application/octet-stream")},
        )
    assert r.status_code == 201
    act_id = r.json()["id"]

    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == act_id)
    ).all()
    assert links == []


from unittest.mock import patch as mock_patch


def test_sync_coros_stamps_default_shoe(session, tmp_path):
    """When _sync_coros ingests a new activity, the default shoe is stamped."""
    from app.routers import sync as sync_mod
    from app.services.fit_parser import FitParseResult

    shoe = _seed_default_shoe(session)

    fake_meta = [{
        "labelId": "test-ext-1",
        "sportType": "100",
        "name": "Test Run",
    }]
    fake_parse = FitParseResult(
        started_at=datetime(2026, 5, 27, 7, 0, 0),
        distance_m=5000,
        duration_s=1500,
        elevation_gain_m=10,
        elevation_loss_m=10,
        avg_hr=140,
        sport_type="run",
        datapoints=[],
        laps=[],
    )
    fake_detail = {"notes": None, "rpe": None}

    with mock_patch.object(sync_mod, "coros_login", return_value=("tok", "uid")), \
         mock_patch.object(sync_mod, "coros_list", return_value=fake_meta), \
         mock_patch.object(sync_mod, "download_fit", return_value=b"\x00\x00"), \
         mock_patch.object(sync_mod, "get_activity_detail", return_value=fake_detail), \
         mock_patch.object(sync_mod, "parse_fit_file", return_value=fake_parse), \
         mock_patch.object(sync_mod, "fetch_weather", return_value=None), \
         mock_patch.object(sync_mod, "bg_rebuild_all", return_value=None), \
         mock_patch.object(sync_mod, "engine", session.bind), \
         mock_patch.object(sync_mod, "DATA_DIR", tmp_path), \
         mock_patch.object(sync_mod, "COROS_EMAIL", "test@example.com"), \
         mock_patch.object(sync_mod, "COROS_PASSWORD", "pw"):
        sync_mod._sync_coros()

    acts = session.exec(select(Activity)).all()
    assert len(acts) == 1
    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == acts[0].id)
    ).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id


def test_strava_streams_import_stamps_default_shoe(session, tmp_path):
    """When _sync_strava_activities imports an unmatched Strava activity, default is stamped."""
    from app.routers import sync as sync_mod

    shoe = _seed_default_shoe(session)

    fake_strava_act = {
        "id": 12345,
        "start_date": "2026-05-27T07:00:00Z",
        "sport_type": "Run",
        "distance": 5000,
        "moving_time": 1500,
        "total_elevation_gain": 10,
        "name": "Test Strava Run",
    }

    with mock_patch.object(sync_mod, "get_access_token", return_value="tok"), \
         mock_patch.object(sync_mod, "fetch_athlete_activities", return_value=[fake_strava_act]), \
         mock_patch.object(sync_mod, "fetch_activity_streams", return_value={}), \
         mock_patch.object(sync_mod, "streams_to_datapoints", return_value=[]), \
         mock_patch.object(sync_mod, "fetch_activity_laps", return_value=[]), \
         mock_patch.object(sync_mod, "sync_photos_for_activity", return_value=0), \
         mock_patch.object(sync_mod, "fetch_weather", return_value=None), \
         mock_patch.object(sync_mod, "bg_rebuild_all", return_value=None), \
         mock_patch.object(sync_mod, "engine", session.bind), \
         mock_patch.object(sync_mod, "STRAVA_REFRESH_TOKEN", "rtok"):
        sync_mod._sync_strava_activities()

    acts = session.exec(select(Activity).where(Activity.strava_id == "12345")).all()
    assert len(acts) == 1
    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == acts[0].id)
    ).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id


import json


def test_rebuild_shoes_emits_is_default(session, tmp_path):
    from app.services.builder import _rebuild_shoes

    a = Shoe(name="A")
    b = Shoe(name="B")
    session.add(a)
    session.add(b)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=a.id))
    session.commit()

    _rebuild_shoes(session, tmp_path)

    data = json.loads((tmp_path / "shoes.json").read_text())
    by_name = {s["name"]: s for s in data}
    assert by_name["A"]["is_default"] is True
    assert by_name["B"]["is_default"] is False


def test_rebuild_shoes_no_default(session, tmp_path):
    from app.services.builder import _rebuild_shoes

    a = Shoe(name="A")
    session.add(a)
    session.add(UserProfile(id=1, default_shoe_id=None))
    session.commit()

    _rebuild_shoes(session, tmp_path)

    data = json.loads((tmp_path / "shoes.json").read_text())
    assert all(s["is_default"] is False for s in data)


def test_strava_sync_does_not_touch_existing_shoes(session, tmp_path):
    """After removal of shoe sync, _sync_strava_activities leaves Shoe/ActivityShoe untouched."""
    from app.routers import sync as sync_mod

    # Seed an existing shoe + link manually
    shoe = Shoe(name="Pre-existing")
    session.add(shoe)
    session.flush()
    act = Activity(
        source="manual_upload",
        started_at=datetime(2026, 5, 26, 7, 0, 0),
        distance_m=5000, duration_s=1500, elevation_gain_m=10,
        sport_type="run",
    )
    session.add(act)
    session.flush()
    session.add(ActivityShoe(activity_id=act.id, shoe_id=shoe.id))
    session.commit()
    initial_shoe_count = len(session.exec(select(Shoe)).all())
    initial_link_count = len(session.exec(select(ActivityShoe)).all())

    with mock_patch.object(sync_mod, "get_access_token", return_value="tok"), \
         mock_patch.object(sync_mod, "fetch_athlete_activities", return_value=[]), \
         mock_patch.object(sync_mod, "sync_photos_for_activity", return_value=0), \
         mock_patch.object(sync_mod, "bg_rebuild_all", return_value=None), \
         mock_patch.object(sync_mod, "engine", session.bind), \
         mock_patch.object(sync_mod, "STRAVA_REFRESH_TOKEN", "rtok"):
        sync_mod._sync_strava_activities()

    assert len(session.exec(select(Shoe)).all()) == initial_shoe_count
    assert len(session.exec(select(ActivityShoe)).all()) == initial_link_count
    assert "shoes_synced" not in sync_mod._last_sync
    assert "shoe_links_created" not in sync_mod._last_sync


def test_patch_profile_triggers_shoes_json_rebuild(client, session):
    """Changing default_shoe_id must rebuild shoes.json synchronously so the
    static is_default values are fresh before the response returns."""
    from app.routers import profile as profile_mod

    shoe = Shoe(name="Pace")
    session.add(shoe)
    session.add(UserProfile(id=1))
    session.commit()
    session.refresh(shoe)

    with mock_patch.object(profile_mod, "_rebuild_shoes") as rebuild:
        r = client.patch("/api/profile", json={"default_shoe_id": shoe.id})
        assert r.status_code == 200
        rebuild.assert_called_once()


def test_patch_profile_skips_rebuild_when_default_unchanged(client, session):
    """Editing only hr_max etc. must NOT trigger a shoes.json rebuild."""
    from app.routers import profile as profile_mod

    session.add(UserProfile(id=1))
    session.commit()

    with mock_patch.object(profile_mod, "_rebuild_shoes") as rebuild:
        r = client.patch("/api/profile", json={"hr_max": 190})
        assert r.status_code == 200
        rebuild.assert_not_called()
