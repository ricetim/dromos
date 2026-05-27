from sqlmodel import Session, select
from app.models import UserProfile, Shoe, ActivityShoe, Activity
from app.services.shoe_default import stamp_default_shoe
from datetime import datetime


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
