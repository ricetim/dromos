import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from app.config import COROS_EMAIL, COROS_PASSWORD, DATA_DIR
from app.database import get_session
from app.models import Activity, ActivityShoe, DataPoint, Photo, Lap, Shoe
from app.services.fit_parser import parse_fit_file
from app.services.builder import bg_rebuild_after_upload, bg_rebuild_after_delete, bg_rebuild_after_activity_update, bg_rebuild_globals, _rebuild_shoes, STATIC_DIR
from app.services.weather import fetch_weather
from app.services.sun import sun_fields
from app.services.coros import login as coros_login, list_activities as coros_list, get_activity_detail
from app.services.shoe_default import stamp_default_shoe
from app.services.eventlog import log_info

router = APIRouter(prefix="/api/activities", tags=["activities"])

# Reads (list, detail, datapoints, track, laps) are served from precompiled
# static JSON written by app.services.builder — nginx/Starlette serve those
# files directly, so they never touch this router. The only live read still
# needed is photos, fetched lazily by the activity detail page.


@router.get("/{activity_id}/photos")
def get_photos(activity_id: int, session: Session = Depends(get_session)):
    if not session.get(Activity, activity_id):
        raise HTTPException(status_code=404, detail="Activity not found")
    return session.exec(
        select(Photo).where(Photo.activity_id == activity_id)
    ).all()


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_fit(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    fit_dir = DATA_DIR / "fit_files"
    fit_dir.mkdir(exist_ok=True)
    dest = fit_dir / f"{uuid.uuid4()}.fit"
    with dest.open("wb") as buf:
        shutil.copyfileobj(file.file, buf)

    try:
        result = parse_fit_file(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Cannot parse FIT file: {e}")

    avg_pace = result.duration_s / (result.distance_m / 1000) if result.distance_m > 0 else None
    act = Activity(
        source="manual_upload",
        started_at=result.started_at,
        distance_m=result.distance_m,
        duration_s=result.duration_s,
        elevation_gain_m=result.elevation_gain_m,
        elevation_loss_m=result.elevation_loss_m,
        avg_hr=result.avg_hr,
        sport_type=result.sport_type,
        fit_file_path=str(dest),
        avg_pace_s_per_km=round(avg_pace, 1) if avg_pace else None,
    )
    session.add(act)
    session.flush()
    stamp_default_shoe(session, act.id)

    for dp in result.datapoints:
        session.add(DataPoint(activity_id=act.id, **dp))
    for lap in result.laps:
        session.add(Lap(
            activity_id=act.id,
            lap_number=lap.lap_number,
            start_elapsed_s=lap.start_elapsed_s,
            end_elapsed_s=lap.end_elapsed_s,
            distance_m=lap.distance_m,
            duration_s=lap.duration_s,
            avg_hr=lap.avg_hr,
            avg_pace_s_per_km=lap.avg_pace_s_per_km,
            elevation_gain_m=lap.elevation_gain_m,
        ))

    session.commit()
    session.refresh(act)

    # Fetch weather from Open-Meteo (non-blocking: failure just leaves fields null)
    first_gps = next(
        (dp for dp in result.datapoints if dp.get("lat") and dp.get("lon")), None
    )
    if first_gps:
        weather = fetch_weather(first_gps["lat"], first_gps["lon"], result.started_at)
        if weather:
            for k, v in weather.items():
                setattr(act, k, v)
        # Sunrise/sunset: computed locally, no network — always set when GPS exists.
        for k, v in sun_fields(first_gps["lat"], first_gps["lon"], result.started_at).items():
            setattr(act, k, v)
        session.add(act)
        session.commit()
        session.refresh(act)

    log_info(
        "upload",
        f"uploaded activity {act.id} "
        f"({(act.distance_m or 0) / 1000:.2f} km @ {act.started_at.isoformat()})",
        {"id": act.id, "distance_m": act.distance_m,
         "started_at": act.started_at.isoformat() if act.started_at else None},
        session=session,
    )
    background_tasks.add_task(bg_rebuild_after_upload, act.id)
    return act


@router.delete("/{activity_id}", status_code=204)
def delete_activity(activity_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")

    # Snapshot identifying details for the log before the row is gone — after
    # the commit below the ORM object is detached and its attributes unreadable.
    n_dp = len(session.exec(select(DataPoint.id).where(DataPoint.activity_id == activity_id)).all())
    n_laps = len(session.exec(select(Lap.id).where(Lap.activity_id == activity_id)).all())
    source = act.source
    distance_km = (act.distance_m or 0) / 1000
    summary = {
        "id": activity_id,
        "source": source,
        "started_at": act.started_at.isoformat() if act.started_at else None,
        "distance_m": act.distance_m,
        "strava_id": act.strava_id,
        "external_id": act.external_id,
        "datapoints": n_dp,
        "laps": n_laps,
    }

    # Bulk-delete related rows — much faster than ORM-level one-by-one deletion.
    # Lap rows are included here; the FK has no cascade, so omitting them would
    # leak orphaned laps that skew per-activity lap views after re-import.
    session.exec(sa_delete(DataPoint).where(DataPoint.activity_id == activity_id))
    session.exec(sa_delete(Lap).where(Lap.activity_id == activity_id))
    session.exec(sa_delete(Photo).where(Photo.activity_id == activity_id))
    session.exec(sa_delete(ActivityShoe).where(ActivityShoe.activity_id == activity_id))
    session.delete(act)
    session.commit()

    log_info(
        "delete",
        f"deleted activity {activity_id} ({source}, "
        f"{distance_km:.2f} km, {n_dp} datapoints, {n_laps} laps)",
        summary,
        session=session,
    )
    background_tasks.add_task(bg_rebuild_after_delete, activity_id)


@router.patch("/{activity_id}")
def update_activity(
    activity_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")
    for key in {"notes", "name", "strava_id", "rpe"}:
        if key in data:
            setattr(act, key, data[key])
    session.add(act)
    session.commit()
    session.refresh(act)
    background_tasks.add_task(bg_rebuild_after_activity_update, activity_id)
    return act


@router.post("/{activity_id}/refresh-coros")
def refresh_from_coros(
    activity_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Re-fetch notes and RPE from Coros for an existing activity."""
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")
    if act.source != "coros" or not act.external_id:
        raise HTTPException(status_code=400, detail="Not a Coros activity")
    if not COROS_EMAIL:
        raise HTTPException(status_code=400, detail="Coros credentials not configured")

    token, user_id = coros_login(COROS_EMAIL, COROS_PASSWORD)

    # Find this activity in the Coros list to get the numeric sportType
    remote = coros_list(token, user_id)
    meta = next((m for m in remote if str(m.get("labelId", "")) == act.external_id), None)
    if not meta:
        raise HTTPException(status_code=404, detail="Activity not found on Coros")

    sport_type_str = str(meta.get("sportType", "100"))
    detail = get_activity_detail(token, user_id, act.external_id, sport_type_str)

    act.notes = detail["notes"]
    act.rpe = detail["rpe"]
    # Also update name if Coros has one and we don't
    coros_name = meta.get("name") or None
    if coros_name and not act.name:
        act.name = coros_name

    session.add(act)
    session.commit()
    session.refresh(act)
    background_tasks.add_task(bg_rebuild_after_activity_update, activity_id)
    return act


@router.patch("/{activity_id}/shoe", status_code=200)
def update_activity_shoe(
    activity_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")

    shoe_id = data.get("shoe_id")
    if shoe_id is not None:
        if not session.get(Shoe, shoe_id):
            raise HTTPException(status_code=404, detail="Shoe not found")

    # Clear all existing shoe associations for this activity
    session.exec(sa_delete(ActivityShoe).where(ActivityShoe.activity_id == activity_id))

    # Assign the new shoe if provided
    if shoe_id is not None:
        session.add(ActivityShoe(activity_id=activity_id, shoe_id=shoe_id))

    session.commit()
    _rebuild_shoes(session, STATIC_DIR)
    background_tasks.add_task(bg_rebuild_after_activity_update, activity_id)
    background_tasks.add_task(bg_rebuild_globals)
    return {"ok": True}
