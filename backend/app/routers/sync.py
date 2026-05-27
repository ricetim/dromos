from fastapi import APIRouter, BackgroundTasks
from sqlmodel import Session, select
from app.database import engine
from app.models import Activity, ActivityShoe, DataPoint, Lap, Shoe
from app.services.strava import (
    get_access_token, fetch_athlete, fetch_athlete_activities, fetch_gear, sync_photos_for_activity,
    fetch_activity_streams, streams_to_datapoints, fetch_activity_laps,
)
from app.services.coros import login as coros_login, list_activities as coros_list
from app.services.coros import download_fit, get_activity_detail
from app.services.fit_parser import parse_fit_file
from app.config import COROS_EMAIL, COROS_PASSWORD, DATA_DIR, STRAVA_REFRESH_TOKEN
from app.services.builder import bg_rebuild_all
from app.services.weather import fetch_weather
from app.services.shoe_default import stamp_default_shoe
from datetime import datetime, timezone
import threading
import uuid

router = APIRouter(prefix="/api/sync", tags=["sync"])
_last_sync: dict = {"status": "never", "ts": None, "error": None}
_sync_lock = threading.Lock()


@router.get("/status")
def status():
    return _last_sync


@router.post("/trigger")
def trigger(bg: BackgroundTasks):
    if _sync_lock.locked():
        return {"message": "sync already in progress"}
    bg.add_task(_sync_strava_activities)
    bg.add_task(_sync_coros)
    return {"message": "sync triggered"}


@router.post("/rebuild")
def rebuild_static(bg: BackgroundTasks):
    """Regenerate all static JSON snapshots from the current database state."""
    bg.add_task(bg_rebuild_all)
    return {"message": "rebuild triggered"}


def _sync_strava_activities() -> None:
    """
    Full Strava sync:
      1. Fetch all athlete activities and match to local activities by start time (±60 s).
      2. Write strava_id on each matched local activity.
      3. Fetch athlete profile → upsert shoes by strava_gear_id.
      4. Link ActivityShoe for every activity that has a Strava gear_id.
      5. Sync photos for all activities that now have a strava_id.
    """
    global _last_sync
    if not STRAVA_REFRESH_TOKEN:
        return
    with _sync_lock, Session(engine) as session:
        try:
            token = get_access_token()

            # ── 1. Fetch Strava activity list ─────────────────────────────
            # Fetch all time (after=0) so pre-Coros Strava history is included.
            strava_acts = fetch_athlete_activities(token, after=0)

            # Build lookup: unix_timestamp → strava activity dict
            def _ts(iso: str) -> int:
                return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())

            strava_by_ts: dict[int, dict] = {_ts(a["start_date"]): a for a in strava_acts}

            # ── 2. Match local activities → strava_id ────────────────────
            local_acts = session.exec(select(Activity)).all()
            matched_count = 0
            # strava_gear_id → list of local activity IDs that used that gear
            gear_map: dict[str, list[int]] = {}

            for act in local_acts:
                local_ts = int(
                    act.started_at.replace(tzinfo=timezone.utc).timestamp()
                    if act.started_at.tzinfo is None
                    else act.started_at.timestamp()
                )
                matched = next(
                    (strava_by_ts[t] for t in range(local_ts - 60, local_ts + 61)
                     if t in strava_by_ts),
                    None,
                )
                if matched is None:
                    continue
                strava_id = str(matched["id"])
                if act.strava_id != strava_id:
                    act.strava_id = strava_id
                    session.add(act)
                    matched_count += 1
                gear_id = matched.get("gear_id") or ""
                if gear_id and act.id:
                    gear_map.setdefault(gear_id, []).append(act.id)

            session.commit()

            # ── 2b. Import unmatched Strava run activities via streams ────────────
            # Run sport types as reported by Strava (sport_type field, newer API).
            _RUN_TYPES = {"Run", "VirtualRun", "TrailRun"}
            existing_strava_ids = {a.strava_id for a in local_acts if a.strava_id}
            unmatched = [
                sa for sa in strava_acts
                if str(sa["id"]) not in existing_strava_ids
                and (
                    sa.get("sport_type") in _RUN_TYPES
                    or sa.get("type") == "Run"
                )
            ]

            streams_imported = 0
            for sa in unmatched:
                strava_id = str(sa["id"])
                started_at = datetime.fromisoformat(
                    sa["start_date"].replace("Z", "+00:00")
                ).replace(tzinfo=None)

                sport_raw = sa.get("sport_type") or sa.get("type") or "run"
                sport_type = sport_raw.lower().replace(" ", "_")
                distance_m = float(sa.get("distance") or 0)
                duration_s = int(sa.get("moving_time") or 0)
                elevation_m = float(sa.get("total_elevation_gain") or 0)
                avg_hr = sa.get("average_heartrate")
                avg_speed = sa.get("average_speed")
                avg_pace = (1000 / avg_speed) if avg_speed and avg_speed > 0 else None

                try:
                    streams = fetch_activity_streams(token, strava_id)
                except Exception:
                    continue

                dps = streams_to_datapoints(streams, started_at)

                act = Activity(
                    source="strava",
                    strava_id=strava_id,
                    started_at=started_at,
                    distance_m=distance_m,
                    duration_s=duration_s,
                    elevation_gain_m=elevation_m,
                    avg_hr=int(avg_hr) if avg_hr else None,
                    avg_pace_s_per_km=round(avg_pace, 1) if avg_pace else None,
                    sport_type=sport_type,
                    name=sa.get("name") or None,
                )
                session.add(act)
                session.flush()

                for dp in dps:
                    session.add(DataPoint(activity_id=act.id, **dp))

                # Fetch and store laps
                try:
                    raw_laps = fetch_activity_laps(token, strava_id)
                    elapsed = 0.0
                    for raw in raw_laps:
                        lap_dur = float(raw.get("elapsed_time") or 0)
                        lap_dist = float(raw.get("distance") or 0)
                        lap_hr = raw.get("average_heartrate")
                        lap_speed = raw.get("average_speed")
                        lap_pace = (1000 / lap_speed) if lap_speed and lap_speed > 0 else None
                        session.add(Lap(
                            activity_id=act.id,
                            lap_number=int(raw.get("lap_index") or 0),
                            start_elapsed_s=elapsed,
                            end_elapsed_s=elapsed + lap_dur,
                            distance_m=lap_dist,
                            duration_s=lap_dur,
                            avg_hr=int(lap_hr) if lap_hr else None,
                            avg_pace_s_per_km=round(lap_pace, 1) if lap_pace else None,
                            elevation_gain_m=float(raw.get("total_elevation_gain") or 0) or None,
                        ))
                        elapsed += lap_dur
                except Exception:
                    pass  # laps are best-effort

                # Add to gear_map if this activity has a gear_id
                gear_id = sa.get("gear_id") or ""
                if gear_id and act.id:
                    gear_map.setdefault(gear_id, []).append(act.id)

                # Fetch weather
                first_gps = next((dp for dp in dps if dp.get("lat") and dp.get("lon")), None)
                if first_gps:
                    weather = fetch_weather(first_gps["lat"], first_gps["lon"], started_at)
                    if weather:
                        for k, v in weather.items():
                            setattr(act, k, v)
                        session.add(act)

                streams_imported += 1

            session.commit()

            # ── 3. Upsert shoes from athlete profile ──────────────────────
            # NOTE: strava_gear_id was dropped from the Shoe model (Task 2).
            # Full Strava gear-sync removal is deferred to Task 9.
            shoes_synced = 0

            # ── 4. Link ActivityShoe via Strava gear_id ───────────────────
            # NOTE: disabled pending Task 9 (strava_gear_id column removed).
            links_created = 0

            # ── 5. Photo sync for all activities with strava_id ───────────
            acts_with_strava = session.exec(
                select(Activity).where(Activity.strava_id.is_not(None))
            ).all()
            new_photos = sum(sync_photos_for_activity(a, session, token) for a in acts_with_strava)

            bg_rebuild_all()

            _last_sync = {
                "status": "ok",
                "ts": datetime.now(timezone.utc).isoformat(),
                "matched_activities": matched_count,
                "strava_activities_imported": streams_imported,
                "shoes_synced": shoes_synced,
                "shoe_links_created": links_created,
                "new_photos": new_photos,
                "error": None,
            }
        except Exception as e:
            _last_sync = {
                "status": "error",
                "ts": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }


def _sync_coros() -> None:
    global _last_sync
    if not COROS_EMAIL:
        return
    with Session(engine) as session:
        try:
            token, user_id = coros_login(COROS_EMAIL, COROS_PASSWORD)
            remote = coros_list(token, user_id)
            existing_acts = {a.external_id: a for a in session.exec(select(Activity)).all()}
            new_count = 0
            for meta in remote:
                ext_id = str(meta.get("labelId", ""))
                sport_type_str = str(meta.get("sportType", "100"))
                activity_name = meta.get("name") or None
                if ext_id in existing_acts:
                    # Backfill name if missing
                    act = existing_acts[ext_id]
                    if act.name is None and activity_name:
                        act.name = activity_name
                        session.add(act)
                    continue
                fit_bytes = download_fit(token, user_id, ext_id, sport_type_str)
                fit_dir = DATA_DIR / "fit_files"
                fit_dir.mkdir(exist_ok=True)
                dest = fit_dir / f"{uuid.uuid4()}.fit"
                dest.write_bytes(fit_bytes)
                result = parse_fit_file(dest)
                detail = get_activity_detail(token, user_id, ext_id, sport_type_str)
                avg_pace = result.duration_s / (result.distance_m / 1000) if result.distance_m > 0 else None
                act = Activity(
                    source="coros", external_id=ext_id,
                    started_at=result.started_at, distance_m=result.distance_m,
                    duration_s=result.duration_s, elevation_gain_m=result.elevation_gain_m,
                    elevation_loss_m=result.elevation_loss_m,
                    avg_hr=result.avg_hr, sport_type=result.sport_type,
                    fit_file_path=str(dest), notes=detail["notes"], rpe=detail["rpe"],
                    name=activity_name,
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
                new_count += 1
                # Fetch weather for new activity
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
            _last_sync = {"status": "ok", "ts": datetime.now(timezone.utc).isoformat(),
                          "new_activities": new_count, "error": None}
            bg_rebuild_all()
        except Exception as e:
            _last_sync = {"status": "error", "ts": datetime.now(timezone.utc).isoformat(),
                          "error": str(e)}
