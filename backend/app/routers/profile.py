from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.models import Shoe, UserProfile
from app.services.builder import STATIC_DIR, _rebuild_shoes

router = APIRouter(prefix="/api/profile", tags=["profile"])

ALLOWED_FIELDS = {"hr_max", "hr_rest", "weight_kg", "default_shoe_id"}


@router.get("")
def get_profile(session: Session = Depends(get_session)):
    profile = session.get(UserProfile, 1)
    return profile or UserProfile(id=1)


@router.patch("")
def update_profile(
    data: dict,
    session: Session = Depends(get_session),
):
    profile = session.get(UserProfile, 1)
    if not profile:
        profile = UserProfile(id=1)
        session.add(profile)

    if "default_shoe_id" in data:
        new_id = data["default_shoe_id"]
        if new_id is not None:
            shoe = session.get(Shoe, new_id)
            if not shoe:
                raise HTTPException(status_code=400, detail="Shoe not found")
            if shoe.retired:
                raise HTTPException(status_code=400, detail="Cannot set retired shoe as default")

    for key in ALLOWED_FIELDS:
        if key in data:
            setattr(profile, key, data[key])

    session.add(profile)
    session.commit()
    session.refresh(profile)

    # is_default in shoes.json is the only static data that depends on
    # default_shoe_id. Rebuild it synchronously so the response is not sent
    # until the file the client re-reads is fresh — otherwise the frontend's
    # post-mutation refetch races an async rebuild and reads the stale flag.
    if "default_shoe_id" in data:
        _rebuild_shoes(session, STATIC_DIR)

    return profile
