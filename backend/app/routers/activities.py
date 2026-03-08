import shutil
import time as _time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from app.config import DATA_DIR
from app.database import get_session
from app.models import Activity, ActivityShoe, DataPoint, Photo, PlannedWorkout, Lap
from app.services.fit_parser import parse_fit_file
from app.services.builder import bg_rebuild_after_upload, bg_rebuild_after_delete, bg_rebuild_after_activity_update
from app.services.weather import fetch_weather

router = APIRouter(prefix="/api/activities", tags=["activities"])

# Server-side cache for the activities list (includes GPS tracks — expensive to build)
_list_cache: dict = {"data": None, "ts": 0.0}
_LIST_TTL = 300  # 5 minutes — activities only change on upload/delete


def _invalidate_list_cache() -> None:
    _list_cache["data"] = None


def warm_cache(session: Session) -> None:
    """Pre-populate the activities list cache. Called at startup."""
    if _list_cache["data"] is not None:
        return
    try:
        list_activities(session)
    except Exception:
        pass  # Don't crash startup if warmup fails


class ActivitySummary(BaseModel):
    id: int
    source: str
    external_id: Optional[str] = None
    strava_id: Optional[str] = None
    started_at: datetime
    distance_m: float
    duration_s: int
    elevation_gain_m: float
    elevation_loss_m: Optional[float] = None
    avg_hr: Optional[int] = None
    avg_pace_s_per_km: Optional[float] = None
    sport_type: str
    notes: Optional[str] = None
    rpe: Optional[int] = None
    name: Optional[str] = None
    track: list[list[float]] = []
    planned_workout_type: Optional[str] = None


def _downsample(points: list[list[float]], max_points: int = 150) -> list[list[float]]:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    indices = {0, len(points) - 1}
    indices.update(int(i * step) for i in range(1, max_points - 1))
    return [points[i] for i in sorted(indices)]


@router.get("", response_model=list[ActivitySummary])
def list_activities(session: Session = Depends(get_session)):
    now = _time.monotonic()
    if _list_cache["data"] is not None and now - _list_cache["ts"] < _LIST_TTL:
        return _list_cache["data"]

    activities = session.exec(
        select(Activity).order_by(Activity.started_at.desc())
    ).all()

    if not activities:
        return []

    activity_ids = [a.id for a in activities]

    # Bulk fetch only lat/lon for all activities (avoids N+1)
    gps_rows = session.exec(
        select(DataPoint.activity_id, DataPoint.lat, DataPoint.lon)
        .where(DataPoint.activity_id.in_(activity_ids))
        .where(DataPoint.lat.is_not(None))
        .where(DataPoint.lon.is_not(None))
        .order_by(DataPoint.activity_id, DataPoint.timestamp)
    ).all()

    gps_by_activity: dict[int, list[list[float]]] = defaultdict(list)
    for row in gps_rows:
        gps_by_activity[row[0]].append([row[1], row[2]])

    # Bulk fetch planned workout types linked to these activities
    planned_rows = session.exec(
        select(PlannedWorkout.completed_activity_id, PlannedWorkout.workout_type)
        .where(PlannedWorkout.completed_activity_id.in_(activity_ids))
    ).all()
    planned_type_by_activity = {row[0]: row[1] for row in planned_rows}

    result = [
        ActivitySummary(
            id=a.id,
            source=a.source,
            external_id=a.external_id,
            strava_id=a.strava_id,
            started_at=a.started_at,
            distance_m=a.distance_m,
            duration_s=a.duration_s,
            elevation_gain_m=a.elevation_gain_m,
            avg_hr=a.avg_hr,
            avg_pace_s_per_km=a.avg_pace_s_per_km,
            sport_type=a.sport_type,
            notes=a.notes,
            rpe=a.rpe,
            name=a.name,
            track=_downsample(gps_by_activity.get(a.id, [])),
            planned_workout_type=planned_type_by_activity.get(a.id),
        )
        for a in activities
    ]
    _list_cache["data"] = result
    _list_cache["ts"] = now
    return result


@router.get("/{activity_id}/full")
def get_activity_full(activity_id: int, session: Session = Depends(get_session)):
    """Combined endpoint: activity + laps + compact track in one request."""
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")
    laps = session.exec(
        select(Lap).where(Lap.activity_id == activity_id).order_by(Lap.lap_number)
    ).all()
    rows = session.exec(
        select(DataPoint.lat, DataPoint.lon, DataPoint.speed_m_s)
        .where(DataPoint.activity_id == activity_id)
        .where(DataPoint.lat.is_not(None))
        .where(DataPoint.lon.is_not(None))
        .order_by(DataPoint.timestamp)
    ).all()
    track = [[r[0], r[1], r[2]] for r in rows]
    return {"activity": act, "laps": laps, "track": track}


@router.get("/{activity_id}", response_model=Activity)
def get_activity(activity_id: int, session: Session = Depends(get_session)):
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")
    return act


@router.get("/{activity_id}/datapoints")
def get_datapoints(activity_id: int, session: Session = Depends(get_session)):
    if not session.get(Activity, activity_id):
        raise HTTPException(status_code=404, detail="Activity not found")
    return session.exec(
        select(DataPoint)
        .where(DataPoint.activity_id == activity_id)
        .order_by(DataPoint.timestamp)
    ).all()


@router.get("/{activity_id}/laps")
def get_laps(activity_id: int, session: Session = Depends(get_session)):
    if not session.get(Activity, activity_id):
        raise HTTPException(status_code=404, detail="Activity not found")
    return session.exec(
        select(Lap)
        .where(Lap.activity_id == activity_id)
        .order_by(Lap.lap_number)
    ).all()


@router.get("/{activity_id}/track")
def get_track(activity_id: int, session: Session = Depends(get_session)):
    """Compact GPS track: [[lat, lon, speed_m_s_or_null], ...] — fast-loading for map."""
    if not session.get(Activity, activity_id):
        raise HTTPException(status_code=404, detail="Activity not found")
    rows = session.exec(
        select(DataPoint.lat, DataPoint.lon, DataPoint.speed_m_s)
        .where(DataPoint.activity_id == activity_id)
        .where(DataPoint.lat.is_not(None))
        .where(DataPoint.lon.is_not(None))
        .order_by(DataPoint.timestamp)
    ).all()
    return [[r[0], r[1], r[2]] for r in rows]


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
    dest = DATA_DIR / f"{uuid.uuid4()}.fit"
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
            session.add(act)
            session.commit()
            session.refresh(act)

    _invalidate_list_cache()
    from app.routers.stats import _invalidate_pb_cache, _invalidate_stats_cache
    _invalidate_pb_cache()
    _invalidate_stats_cache()
    background_tasks.add_task(bg_rebuild_after_upload, act.id)
    return act


@router.delete("/{activity_id}", status_code=204)
def delete_activity(activity_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")
    # Bulk-delete related rows — much faster than ORM-level one-by-one deletion
    session.exec(sa_delete(DataPoint).where(DataPoint.activity_id == activity_id))
    session.exec(sa_delete(Photo).where(Photo.activity_id == activity_id))
    session.exec(sa_delete(ActivityShoe).where(ActivityShoe.activity_id == activity_id))
    session.delete(act)
    session.commit()
    _invalidate_list_cache()
    from app.routers.stats import _invalidate_pb_cache, _invalidate_stats_cache
    _invalidate_pb_cache()
    _invalidate_stats_cache()
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
    for key in {"notes", "strava_id", "rpe"}:
        if key in data:
            setattr(act, key, data[key])
    session.add(act)
    session.commit()
    session.refresh(act)
    _invalidate_list_cache()
    background_tasks.add_task(bg_rebuild_after_activity_update, activity_id)
    return act
