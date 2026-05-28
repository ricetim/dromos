from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.models import Shoe, UserProfile
from app.services.builder import bg_rebuild_globals

router = APIRouter(prefix="/api/profile", tags=["profile"])

ALLOWED_FIELDS = {"hr_max", "hr_rest", "weight_kg", "default_shoe_id"}


@router.get("")
def get_profile(session: Session = Depends(get_session)):
    profile = session.get(UserProfile, 1)
    return profile or UserProfile(id=1)


@router.patch("")
def update_profile(
    data: dict,
    background_tasks: BackgroundTasks,
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

    # is_default in shoes.json depends on default_shoe_id; regenerate so the
    # frontend's static fetch reflects the change immediately.
    if "default_shoe_id" in data:
        background_tasks.add_task(bg_rebuild_globals)

    return profile
