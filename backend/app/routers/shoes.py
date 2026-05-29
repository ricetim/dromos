from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session, select, func
from app.database import get_session
from app.models import Shoe, ActivityShoe, Activity
from app.services.builder import STATIC_DIR, _rebuild_shoes, bg_rebuild_globals

router = APIRouter(prefix="/api/shoes", tags=["shoes"])


@router.get("")
def list_shoes(session: Session = Depends(get_session)):
    shoes = session.exec(select(Shoe)).all()
    # Single aggregation query instead of N+1 per shoe
    dist_rows = session.exec(
        select(ActivityShoe.shoe_id, func.sum(Activity.distance_m))
        .join(Activity, Activity.id == ActivityShoe.activity_id)
        .group_by(ActivityShoe.shoe_id)
    ).all()
    dist_by_shoe = {row[0]: row[1] or 0.0 for row in dist_rows}
    return [
        {**shoe.model_dump(), "total_distance_km": round(dist_by_shoe.get(shoe.id, 0.0) / 1000, 1)}
        for shoe in shoes
    ]


@router.post("", status_code=201)
def create_shoe(shoe: Shoe, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    session.add(shoe)
    session.commit()
    session.refresh(shoe)
    # Rebuild shoes.json / shoes_timeline.json synchronously so the new shoe is
    # present before the response returns; the broader globals refresh can lag.
    _rebuild_shoes(session, STATIC_DIR)
    background_tasks.add_task(bg_rebuild_globals)
    return shoe


@router.patch("/{shoe_id}")
def update_shoe(shoe_id: int, data: dict, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    shoe = session.get(Shoe, shoe_id)
    if not shoe:
        raise HTTPException(status_code=404)
    for k in {"name", "brand", "retired", "notes", "retirement_threshold_km"}:
        if k in data:
            setattr(shoe, k, data[k])
    # If this shoe just became retired and is the current default, clear the default.
    if shoe.retired:
        from app.models import UserProfile
        profile = session.get(UserProfile, 1)
        if profile and profile.default_shoe_id == shoe.id:
            profile.default_shoe_id = None
            session.add(profile)
    session.add(shoe)
    session.commit()
    session.refresh(shoe)
    # Rebuild shoes.json / shoes_timeline.json synchronously so retire/rename is
    # reflected before the response returns (the frontend reconciles its
    # optimistic update against these files). bg_rebuild_globals still refreshes
    # activities.json's shoe_names in the background.
    _rebuild_shoes(session, STATIC_DIR)
    background_tasks.add_task(bg_rebuild_globals)
    return shoe
