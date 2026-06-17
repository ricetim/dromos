from fastapi import APIRouter, BackgroundTasks
from sqlmodel import Session, select
from app.database import engine
from app.models import Activity, DataPoint, Lap
from app.services.strava import (
    get_access_token, fetch_athlete_activities, sync_photos_for_activity,
    fetch_activity_streams, streams_to_datapoints, fetch_activity_laps,
)
from app.services.coros import login as coros_login, list_activities as coros_list
from app.services.coros import download_fit, get_activity_detail
from app.services.fit_parser import parse_fit_file
from app.config import COROS_EMAIL, COROS_PASSWORD, DATA_DIR, STRAVA_REFRESH_TOKEN
from app.services.builder import bg_rebuild_all
from app.services.weather import fetch_weather
from app.services.sun import sun_fields
from app.services.shoe_default import stamp_default_shoe
from app.services.eventlog import log_info, log_warning, log_error
from app.services.dedup import (
    LocalCandidate, TIME_MATCH_S, best_fallback_match, closest_in_window,
)
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
    log_info("sync", "manual sync triggered")
    bg.add_task(_sync_strava_activities)
    bg.add_task(_sync_coros)
    return {"message": "sync triggered"}


@router.post("/rebuild")
def rebuild_static(bg: BackgroundTasks):
    """Regenerate all static JSON snapshots from the current database state."""
    log_info("rebuild", "manual static rebuild triggered")
    bg.add_task(bg_rebuild_all)
    return {"message": "rebuild triggered"}


def _sync_strava_activities() -> None:
    """
    Full Strava sync:
      1. Fetch all athlete activities and match to local activities by start time (±60 s).
      2. Write strava_id on each matched local activity.
      3. Import any unmatched Strava run activities via stream API (+ default-shoe stamp).
      4. Sync photos for all activities that now have a strava_id.
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
            log_info("sync.strava",
                     f"sync started: fetched {len(strava_acts)} strava activities")

            # Build lookup: unix_timestamp → strava activity dict
            def _ts(iso: str) -> int:
                return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())

            def _local_ts(a: Activity) -> int:
                return int(
                    a.started_at.replace(tzinfo=timezone.utc).timestamp()
                    if a.started_at.tzinfo is None
                    else a.started_at.timestamp()
                )

            strava_by_ts: dict[int, dict] = {_ts(a["start_date"]): a for a in strava_acts}

            # ── 2. Match local activities → strava_id (time match) ───────
            local_acts = session.exec(select(Activity)).all()
            matched_count = 0

            for act in local_acts:
                local_ts = _local_ts(act)
                matched = next(
                    (strava_by_ts[t]
                     for t in range(local_ts - TIME_MATCH_S, local_ts + TIME_MATCH_S + 1)
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

            # Local activities still lacking a strava_id are candidates for the
            # distance-based fallback: a Coros run whose start time drifted past
            # the time-match window should still adopt its Strava twin rather
            # than be duplicated. Keyed by id so an adopted local is removed.
            cand_pool: dict[int, LocalCandidate] = {
                a.id: LocalCandidate(id=a.id, start_ts=_local_ts(a),
                                     distance_m=a.distance_m or 0.0)
                for a in local_acts if not a.strava_id
            }
            locals_by_id = {a.id: a for a in local_acts if not a.strava_id}

            streams_imported = 0
            adopted_count = 0
            for sa in unmatched:
                strava_id = str(sa["id"])
                started_at = datetime.fromisoformat(
                    sa["start_date"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
                s_ts = _ts(sa["start_date"])
                s_dist = float(sa.get("distance") or 0)

                # Distance fallback — adopt onto an existing local run instead of
                # importing a duplicate when start times drifted.
                cand, dt = best_fallback_match(s_ts, s_dist, cand_pool.values())
                if cand is not None:
                    local = locals_by_id[cand.id]
                    local.strava_id = strava_id
                    session.add(local)
                    del cand_pool[cand.id]   # don't let another strava act reuse it
                    adopted_count += 1
                    log_warning(
                        "sync.strava",
                        f"adopted strava {strava_id} onto local activity {cand.id} "
                        f"by distance fallback (Δt={dt}s, beyond the {TIME_MATCH_S}s "
                        f"time window) — not importing a duplicate",
                        {"strava_id": strava_id, "local_id": cand.id, "delta_s": dt,
                         "strava_distance_m": round(s_dist),
                         "local_distance_m": round(cand.distance_m)},
                    )
                    continue

                # No distance match — flag the closest local (if any) so a true
                # duplicate is easy to spot before it silently lands.
                near, near_dt = closest_in_window(s_ts, cand_pool.values())
                if near is not None:
                    log_warning(
                        "sync.strava",
                        f"importing strava {strava_id} as NEW — nearest local "
                        f"{near.id} is Δt={near_dt}s away but distances differ "
                        f"({round(s_dist)}m vs {round(near.distance_m)}m); "
                        f"verify this is not a duplicate",
                        {"strava_id": strava_id, "closest_local_id": near.id,
                         "delta_s": near_dt, "strava_distance_m": round(s_dist),
                         "local_distance_m": round(near.distance_m)},
                    )

                sport_raw = sa.get("sport_type") or sa.get("type") or "run"
                sport_type = sport_raw.lower().replace(" ", "_")
                distance_m = s_dist
                duration_s = int(sa.get("moving_time") or 0)
                elevation_m = float(sa.get("total_elevation_gain") or 0)
                avg_hr = sa.get("average_heartrate")
                avg_speed = sa.get("average_speed")
                avg_pace = (1000 / avg_speed) if avg_speed and avg_speed > 0 else None

                try:
                    streams = fetch_activity_streams(token, strava_id)
                except Exception as exc:
                    log_warning("sync.strava",
                                f"skipped strava {strava_id}: stream fetch failed: {exc}",
                                {"strava_id": strava_id})
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
                stamp_default_shoe(session, act.id)

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
                except Exception as exc:
                    log_warning("sync.strava",
                                f"laps unavailable for strava {strava_id}: {exc}",
                                {"strava_id": strava_id})  # best-effort

                # Fetch weather
                first_gps = next((dp for dp in dps if dp.get("lat") and dp.get("lon")), None)
                if first_gps:
                    weather = fetch_weather(first_gps["lat"], first_gps["lon"], started_at)
                    if weather:
                        for k, v in weather.items():
                            setattr(act, k, v)
                    for k, v in sun_fields(first_gps["lat"], first_gps["lon"], started_at).items():
                        setattr(act, k, v)
                    session.add(act)

                streams_imported += 1
                log_info(
                    "sync.strava",
                    f"imported strava {strava_id} as new activity {act.id} "
                    f"({distance_m / 1000:.2f} km @ {started_at.isoformat()})",
                    {"strava_id": strava_id, "activity_id": act.id,
                     "distance_m": round(distance_m)},
                )

            session.commit()

            # ── 3. Photo sync for all activities with strava_id ───────────
            acts_with_strava = session.exec(
                select(Activity).where(Activity.strava_id.is_not(None))
            ).all()
            new_photos = sum(sync_photos_for_activity(a, session, token) for a in acts_with_strava)

            bg_rebuild_all()

            _last_sync = {
                "status": "ok",
                "ts": datetime.now(timezone.utc).isoformat(),
                "matched_activities": matched_count,
                "strava_activities_adopted": adopted_count,
                "strava_activities_imported": streams_imported,
                "new_photos": new_photos,
                "error": None,
            }
            log_info(
                "sync.strava",
                f"sync complete: matched={matched_count}, adopted={adopted_count}, "
                f"imported={streams_imported}, new_photos={new_photos}",
                _last_sync,
            )
        except Exception as e:
            _last_sync = {
                "status": "error",
                "ts": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }
            log_error("sync.strava", f"sync failed: {e}")


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
            log_info("sync.coros",
                     f"sync started: {len(remote)} activities listed on coros")
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
                log_info(
                    "sync.coros",
                    f"imported coros {ext_id} as new activity {act.id} "
                    f"({(result.distance_m or 0) / 1000:.2f} km @ {result.started_at.isoformat()})",
                    {"external_id": ext_id, "activity_id": act.id,
                     "distance_m": round(result.distance_m or 0)},
                )
                # Fetch weather for new activity
                first_gps = next(
                    (dp for dp in result.datapoints if dp.get("lat") and dp.get("lon")), None
                )
                if first_gps:
                    weather = fetch_weather(first_gps["lat"], first_gps["lon"], result.started_at)
                    if weather:
                        for k, v in weather.items():
                            setattr(act, k, v)
                    for k, v in sun_fields(first_gps["lat"], first_gps["lon"], result.started_at).items():
                        setattr(act, k, v)
                    session.add(act)
            session.commit()
            _last_sync = {"status": "ok", "ts": datetime.now(timezone.utc).isoformat(),
                          "new_activities": new_count, "error": None}
            log_info("sync.coros", f"sync complete: {new_count} new activities", _last_sync)
            bg_rebuild_all()
        except Exception as e:
            _last_sync = {"status": "error", "ts": datetime.now(timezone.utc).isoformat(),
                          "error": str(e)}
            log_error("sync.coros", f"sync failed: {e}")
