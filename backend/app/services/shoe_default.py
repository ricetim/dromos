from sqlmodel import Session
from app.models import ActivityShoe, UserProfile


def stamp_default_shoe(session: Session, activity_id: int) -> None:
    """If the user has a default shoe configured, write a single ActivityShoe
    link for the given activity. Caller must `session.commit()` afterwards.

    No-op when no default is set or no UserProfile row exists. Relies on the
    unique index `idx_activityshoe_activity_id_unique` to prevent duplicates
    if accidentally called twice for the same activity.
    """
    profile = session.get(UserProfile, 1)
    if profile and profile.default_shoe_id:
        session.add(ActivityShoe(
            activity_id=activity_id,
            shoe_id=profile.default_shoe_id,
        ))
