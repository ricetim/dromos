from sqlmodel import Session, select
from app.models import UserProfile, Shoe


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
