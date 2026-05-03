# Strava Historical Import Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Import historical Strava run activities (not in Coros) with GPS streams, weather, and per-mile laps.

**Architecture:** Two small edits — add `fetch_activity_laps()` to the Strava service, then patch section 2b of `_sync_strava_activities` in the sync router: remove the 50-cap, filter to run types only, and persist laps after datapoints.

**Tech Stack:** FastAPI, SQLModel/SQLite, httpx, Strava REST API v3

---

### Task 1: Add `fetch_activity_laps` to strava service

**Files:**
- Modify: `backend/app/services/strava.py`
- Test: `backend/tests/test_strava.py`

**Step 1: Write the failing test**

Add to `backend/tests/test_strava.py`:

```python
from app.services.strava import fetch_activity_laps

def test_fetch_activity_laps():
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = [
        {
            "lap_index": 1,
            "elapsed_time": 482,
            "distance": 1609.34,
            "average_heartrate": 148.5,
            "average_speed": 3.34,
            "total_elevation_gain": 5.2,
            "start_date": "2025-09-15T13:00:00Z",
        }
    ]
    with patch("httpx.get", return_value=mock):
        laps = fetch_activity_laps("token", "99999")
    assert len(laps) == 1
    assert laps[0]["lap_index"] == 1
    assert laps[0]["elapsed_time"] == 482
```

**Step 2: Run to verify it fails**

```bash
cd backend && python3 -m pytest tests/test_strava.py::test_fetch_activity_laps -v
```
Expected: `ImportError` or `AttributeError` — `fetch_activity_laps` doesn't exist yet.

**Step 3: Implement `fetch_activity_laps`**

Add to `backend/app/services/strava.py` after `fetch_activity_streams`:

```python
def fetch_activity_laps(access_token: str, strava_activity_id: str) -> list[dict]:
    """Fetch laps for a Strava activity. Returns raw lap dicts."""
    r = httpx.get(
        f"{_API}/activities/{strava_activity_id}/laps",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    _check(r)
    data = r.json()
    return data if isinstance(data, list) else []
```

**Step 4: Run test to verify it passes**

```bash
cd backend && python3 -m pytest tests/test_strava.py::test_fetch_activity_laps -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/strava.py backend/tests/test_strava.py
git commit -m "feat: add fetch_activity_laps to strava service"
```

---

### Task 2: Patch sync section 2b — filter runs, remove cap, import laps

**Files:**
- Modify: `backend/app/routers/sync.py:112-180`

**Step 1: Update the import at the top of sync.py**

In `backend/app/routers/sync.py`, add `fetch_activity_laps` to the import:

```python
from app.services.strava import (
    get_access_token, fetch_athlete, fetch_athlete_activities, fetch_gear, sync_photos_for_activity,
    fetch_activity_streams, streams_to_datapoints, fetch_activity_laps,
)
```

**Step 2: Replace section 2b in `_sync_strava_activities`**

Replace the block starting at `# ── 2b. Import unmatched Strava activities via streams ────────────` through `session.commit()` (the one after `streams_imported += 1`) with:

```python
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
```

**Step 3: Run the full test suite**

```bash
cd backend && python3 -m pytest -v
```
Expected: all 58 tests pass (no new tests needed for this step — sync logic is integration-level).

**Step 4: Commit**

```bash
git add backend/app/routers/sync.py
git commit -m "feat: import historical Strava runs with laps, remove 50-cap, filter to runs only"
```

---

### Task 3: Rebuild Docker and trigger sync

**Step 1: Rebuild backend image**

```bash
cd /home/tim/projects/runscribe
docker build -t runscribe-backend ./backend
```

**Step 2: Restart containers**

```bash
docker compose down && docker compose up -d
```

**Step 3: Tail backend logs**

```bash
docker compose logs -f backend
```

**Step 4: Trigger sync**

In a second terminal:

```bash
curl -X POST http://localhost:8000/api/sync/trigger
```

**Step 5: Check result**

```bash
curl http://localhost:8000/api/sync/status | python3 -m json.tool
```

Look for `strava_activities_imported` count. If any errors appear in logs, note them for debugging.
