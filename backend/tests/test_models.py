from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Activity, ActivityShoe, Photo, Shoe


def test_create_activity(session):
    act = Activity(
        source="manual_upload",
        started_at=datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc),
        distance_m=10000.0,
        duration_s=3600,
        sport_type="run",
    )
    session.add(act)
    session.commit()
    session.refresh(act)
    assert act.id is not None
    assert act.distance_m == 10000.0


def test_photo_has_gps_fields(session):
    act = Activity(source="manual_upload", started_at=datetime.now(timezone.utc),
                   distance_m=5000, duration_s=1800, sport_type="run")
    session.add(act)
    session.commit()
    photo = Photo(activity_id=act.id, url="https://example.com/photo.jpg",
                  lat=37.7749, lon=-122.4194)
    session.add(photo)
    session.commit()
    session.refresh(photo)
    assert photo.lat == 37.7749
    assert photo.lon == -122.4194


def test_activityshoe_unique_per_activity(session):
    """The unique constraint on activity_id rejects a second link for the same activity."""
    act = Activity(source="manual_upload", started_at=datetime.now(timezone.utc),
                   distance_m=5000, duration_s=1800, sport_type="run")
    s1 = Shoe(name="Shoe A", retirement_threshold_km=800.0)
    s2 = Shoe(name="Shoe B", retirement_threshold_km=800.0)
    session.add_all([act, s1, s2])
    session.commit()

    session.add(ActivityShoe(activity_id=act.id, shoe_id=s1.id))
    session.commit()

    session.add(ActivityShoe(activity_id=act.id, shoe_id=s2.id))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


