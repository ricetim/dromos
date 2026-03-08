# Weather, Per-Mile Laps, and Metrics Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add weather data to every run, synthesize per-mile lap splits for single-lap activities, and rebuild the Fitness page as a Metrics page with Eddington number history and yearly mileage overlay charts.

**Architecture:** All new data is computed and stored at write time (upload/sync); static JSON snapshots are rebuilt via `builder.py` so reads stay at nginx speed. Weather uses the Open-Meteo Archive API (no key, free). Per-mile laps replace device laps in `fit_parser.py` before DB insertion. Eddington and yearly data are stored as new static snapshots (`metrics.json`).

**Tech Stack:** Python 3.11, FastAPI, SQLModel/SQLite, httpx, fitdecode, React 18, TypeScript, Recharts, Tailwind CSS

---

## Task 1: Weather service

**Files:**
- Create: `backend/app/services/weather.py`
- Test: `backend/tests/test_weather.py`

**Context:**
Open-Meteo Archive endpoint: `https://archive-api.open-meteo.com/v1/archive`

WMO weather code groups (for `weather_condition` label):
- 0 → "Clear"
- 1,2 → "Partly cloudy"
- 3 → "Overcast"
- 45,48 → "Fog"
- 51,53,55,56,57,61,63,65,66,67,80,81,82 → "Rain"
- 71,73,75,77,85,86 → "Snow"
- 95,96,99 → "Thunderstorm"

**Step 1: Write failing tests**

```python
# backend/tests/test_weather.py
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from app.services.weather import fetch_weather, _wmo_label


def test_wmo_label_clear():
    assert _wmo_label(0) == "Clear"

def test_wmo_label_rain():
    assert _wmo_label(61) == "Rain"

def test_wmo_label_snow():
    assert _wmo_label(75) == "Snow"

def test_wmo_label_unknown():
    assert _wmo_label(999) == "Unknown"


def _mock_response(hourly_hour: int = 8):
    """Build a fake Open-Meteo JSON payload."""
    return {
        "hourly": {
            "time": [f"2024-05-01T{h:02d}:00" for h in range(24)],
            "temperature_2m":      [15.0] * 24,
            "apparent_temperature": [13.0] * 24,
            "precipitation":       [0.0] * 24,
            "cloudcover":          [20] * 24,
            "windspeed_10m":       [12.0] * 24,
            "weathercode":         [0] * 24,
        },
        "daily": {
            "sunrise": ["2024-05-01T05:30"],
            "sunset":  ["2024-05-01T20:15"],
        },
    }


def test_fetch_weather_returns_dict():
    started_at = datetime(2024, 5, 1, 8, 0, tzinfo=timezone.utc)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_response()
    with patch("httpx.get", return_value=mock_resp):
        result = fetch_weather(51.5, -0.1, started_at)
    assert result is not None
    assert result["weather_temp_c"] == 15.0
    assert result["weather_condition"] == "Clear"
    assert result["weather_is_daytime"] is True


def test_fetch_weather_returns_none_on_error():
    started_at = datetime(2024, 5, 1, 8, 0, tzinfo=timezone.utc)
    with patch("httpx.get", side_effect=Exception("network error")):
        result = fetch_weather(51.5, -0.1, started_at)
    assert result is None


def test_fetch_weather_before_sunrise():
    started_at = datetime(2024, 5, 1, 4, 0, tzinfo=timezone.utc)  # before 05:30
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_response()
    with patch("httpx.get", return_value=mock_resp):
        result = fetch_weather(51.5, -0.1, started_at)
    assert result["weather_is_daytime"] is False
```

**Step 2: Run to verify failure**

```bash
cd backend && python3 -m pytest tests/test_weather.py -v
```
Expected: `ImportError` — module doesn't exist yet.

**Step 3: Implement the service**

```python
# backend/app/services/weather.py
import httpx
from datetime import datetime, timezone

_WMO: dict[int, str] = {
    0: "Clear",
    1: "Partly cloudy", 2: "Partly cloudy",
    3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Rain", 53: "Rain", 55: "Rain",
    56: "Rain", 57: "Rain",
    61: "Rain", 63: "Rain", 65: "Rain",
    66: "Rain", 67: "Rain",
    71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow",
    80: "Rain", 81: "Rain", 82: "Rain",
    85: "Snow", 86: "Snow",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}


def _wmo_label(code: int) -> str:
    return _WMO.get(code, "Unknown")


def fetch_weather(lat: float, lon: float, started_at: datetime) -> dict | None:
    """
    Fetch hourly weather for the run's start location and time from Open-Meteo Archive.
    Returns a dict of weather fields ready to set on an Activity, or None on failure.
    """
    try:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        day = started_at.date().isoformat()
        r = httpx.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "start_date": day,
                "end_date": day,
                "hourly": "temperature_2m,apparent_temperature,precipitation,cloudcover,windspeed_10m,weathercode",
                "daily": "sunrise,sunset",
                "timezone": "auto",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()

        hourly = data["hourly"]
        times = hourly["time"]  # list of "YYYY-MM-DDTHH:MM" strings

        # Find the index whose hour matches the run's start hour (local time approximation via UTC hour)
        run_hour = started_at.hour
        idx = next(
            (i for i, t in enumerate(times) if int(t[11:13]) == run_hour),
            0,
        )

        daily = data.get("daily", {})
        sunrise_str = (daily.get("sunrise") or [""])[0]  # "YYYY-MM-DDTHH:MM"
        sunset_str  = (daily.get("sunset")  or [""])[0]

        is_daytime = False
        if sunrise_str and sunset_str:
            def _parse_local(s: str) -> int:
                """Return hour integer from 'YYYY-MM-DDTHH:MM'."""
                return int(s[11:13]) * 60 + int(s[14:16])
            run_minutes = run_hour * 60 + started_at.minute
            is_daytime = _parse_local(sunrise_str) <= run_minutes <= _parse_local(sunset_str)

        wmo_code = int(hourly["weathercode"][idx] or 0)
        return {
            "weather_temp_c":      hourly["temperature_2m"][idx],
            "weather_feels_like_c": hourly["apparent_temperature"][idx],
            "weather_precip_mm":   hourly["precipitation"][idx],
            "weather_cloud_pct":   int(hourly["cloudcover"][idx] or 0),
            "weather_wind_kph":    hourly["windspeed_10m"][idx],
            "weather_condition":   _wmo_label(wmo_code),
            "weather_is_daytime":  is_daytime,
        }
    except Exception:
        return None  # weather is non-critical; never block upload
```

**Step 4: Run tests to verify passing**

```bash
cd backend && python3 -m pytest tests/test_weather.py -v
```
Expected: 6 tests pass.

**Step 5: Commit**

```bash
git add backend/app/services/weather.py backend/tests/test_weather.py
git commit -m "feat: add Open-Meteo weather service with WMO code mapping"
```

---

## Task 2: Add weather columns to Activity model

**Files:**
- Modify: `backend/app/models.py:6-26`

**Context:** SQLite + SQLModel uses `SQLModel.metadata.create_all(engine)` in `database.py` at startup, which adds new nullable columns automatically to an existing table via `ALTER TABLE`. No migration script needed for SQLite.

**Step 1: Add 7 nullable columns to the Activity class**

In `backend/app/models.py`, add after `name: Optional[str] = None` (line 22):

```python
    # Weather at run time (fetched from Open-Meteo at upload)
    weather_temp_c: Optional[float] = None
    weather_feels_like_c: Optional[float] = None
    weather_precip_mm: Optional[float] = None
    weather_cloud_pct: Optional[int] = None
    weather_wind_kph: Optional[float] = None
    weather_condition: Optional[str] = None
    weather_is_daytime: Optional[bool] = None
```

**Step 2: Update frontend Activity type**

In `frontend/src/types/index.ts`, add after `name?: string | null;` (line 16):

```typescript
  weather_temp_c?: number | null;
  weather_feels_like_c?: number | null;
  weather_precip_mm?: number | null;
  weather_cloud_pct?: number | null;
  weather_wind_kph?: number | null;
  weather_condition?: string | null;
  weather_is_daytime?: boolean | null;
```

**Step 3: Verify the model test still passes**

```bash
cd backend && python3 -m pytest tests/test_models.py -v
```
Expected: all pass.

**Step 4: Commit**

```bash
git add backend/app/models.py frontend/src/types/index.ts
git commit -m "feat: add weather columns to Activity model and TS type"
```

---

## Task 3: Fetch weather at upload and Coros sync

**Files:**
- Modify: `backend/app/routers/activities.py:205-258` (upload_fit)
- Modify: `backend/app/routers/sync.py:192-226` (_sync_coros)

**Context:** `fetch_weather` needs the first GPS DataPoint lat/lon. At upload time, `result.datapoints` is already in memory. Call `fetch_weather` before the background rebuild, then `session.add(act); session.commit()` to persist weather fields.

**Step 1: Add weather fetch to upload_fit**

In `backend/app/routers/activities.py`, add import at top of file (with other service imports):

```python
from app.services.weather import fetch_weather
```

After `session.commit()` and `session.refresh(act)` (after line 253), before `_invalidate_list_cache()`, insert:

```python
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
```

**Step 2: Add weather fetch to _sync_coros**

In `backend/app/routers/sync.py`, after each new activity is committed (after `new_count += 1`), within the `for meta in remote:` loop, insert:

```python
                # Fetch weather for new activity
                first_gps = next(
                    (dp for dp in result.datapoints if dp.get("lat") and dp.get("lon")), None
                )
                if first_gps:
                    from app.services.weather import fetch_weather
                    weather = fetch_weather(first_gps["lat"], first_gps["lon"], result.started_at)
                    if weather:
                        for k, v in weather.items():
                            setattr(act, k, v)
                        session.add(act)
```

Then add `session.commit()` is already called at the end of the loop block — the weather fields will be included.

**Step 3: Verify existing activity tests still pass**

```bash
cd backend && python3 -m pytest tests/test_activities.py -v
```
Expected: all pass (weather fetch will silently fail in test env — no network).

**Step 4: Commit**

```bash
git add backend/app/routers/activities.py backend/app/routers/sync.py
git commit -m "feat: fetch and store weather at activity upload and Coros sync"
```

---

## Task 4: Per-mile lap synthesis in fit_parser

**Files:**
- Modify: `backend/app/services/fit_parser.py:136-170`
- Test: `backend/tests/test_fit_parser.py`

**Context:** After the existing lap-building loop (line 136–158), if `len(laps) == 1`, replace `laps` with synthetic mile splits computed from `datapoints`. A mile is 1609.344 m. Walk through DataPoints in order; at each mile boundary emit a lap. If remaining distance after last full mile is > 50 m, emit a partial lap.

**Step 1: Write failing tests**

Add to `backend/tests/test_fit_parser.py`:

```python
from datetime import datetime, timezone, timedelta
from app.services.fit_parser import _synthesize_mile_laps, LapData


def _make_dps(total_m: float, step_m: float = 100.0, hr: int = 150):
    """Create synthetic datapoints at regular distance/time intervals."""
    dps = []
    t0 = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    d = 0.0
    i = 0
    while d <= total_m + step_m:
        dps.append({
            "timestamp": t0 + timedelta(seconds=i * 10),
            "distance_m": round(d, 1),
            "heart_rate": hr,
            "altitude_m": 50.0 + (d * 0.005),  # gentle climb
        })
        d += step_m
        i += 1
    return dps


def test_synthesize_two_full_miles():
    dps = _make_dps(3500.0)  # ~2.17 miles
    laps = _synthesize_mile_laps(dps)
    assert len(laps) == 3  # mile 1, mile 2, partial
    assert laps[0].lap_number == 1
    assert abs(laps[0].distance_m - 1609.344) < 1.0
    assert laps[1].lap_number == 2
    assert laps[2].distance_m < 1609.344  # partial


def test_synthesize_exact_one_mile():
    dps = _make_dps(1609.344)
    laps = _synthesize_mile_laps(dps)
    assert len(laps) == 1
    assert abs(laps[0].distance_m - 1609.344) < 1.0


def test_synthesize_ignores_tiny_remainder():
    """Remainder < 50m should not produce an extra lap."""
    dps = _make_dps(1620.0)  # 1 mile + 10.7m remainder — below threshold
    laps = _synthesize_mile_laps(dps)
    assert len(laps) == 1


def test_synthesize_avg_hr():
    dps = _make_dps(2000.0, hr=160)
    laps = _synthesize_mile_laps(dps)
    assert laps[0].avg_hr == 160


def test_synthesize_empty_returns_empty():
    assert _synthesize_mile_laps([]) == []
```

**Step 2: Run to verify failure**

```bash
cd backend && python3 -m pytest tests/test_fit_parser.py::test_synthesize_two_full_miles -v
```
Expected: `ImportError: cannot import name '_synthesize_mile_laps'`

**Step 3: Implement `_synthesize_mile_laps` in fit_parser.py**

Add this function before `parse_fit_file` (after the `_tz` helper, around line 47):

```python
_MILE_M = 1609.344
_MIN_PARTIAL_M = 50.0


def _synthesize_mile_laps(datapoints: list[dict]) -> list["LapData"]:
    """
    Build per-mile LapData from a DataPoints list.
    Called when a FIT file has only one device lap (i.e. the whole run is one lap).
    Requires datapoints sorted by timestamp with distance_m populated.
    """
    pts = [
        dp for dp in datapoints
        if dp.get("distance_m") is not None and dp.get("timestamp") is not None
    ]
    if not pts:
        return []

    laps: list[LapData] = []
    lap_num = 0
    next_boundary = _MILE_M
    lap_start_idx = 0
    t0 = pts[0]["timestamp"]

    def _emit(start_i: int, end_i: int, dist: float) -> LapData:
        nonlocal lap_num
        lap_num += 1
        slice_ = pts[start_i:end_i + 1]
        t_start = (slice_[0]["timestamp"] - t0).total_seconds()
        t_end   = (slice_[-1]["timestamp"] - t0).total_seconds()
        dur = t_end - t_start

        hrs = [dp["heart_rate"] for dp in slice_ if dp.get("heart_rate")]
        avg_hr = int(sum(hrs) / len(hrs)) if hrs else None

        alts = [dp["altitude_m"] for dp in slice_ if dp.get("altitude_m") is not None]
        elev_gain = sum(
            max(0.0, alts[i + 1] - alts[i]) for i in range(len(alts) - 1)
        ) if len(alts) > 1 else 0.0

        pace = (1000.0 / (dist / dur)) if dur > 0 and dist > 0 else None
        return LapData(
            lap_number=lap_num,
            start_elapsed_s=round(t_start, 1),
            end_elapsed_s=round(t_end, 1),
            distance_m=round(dist, 1),
            duration_s=round(dur, 1),
            avg_hr=avg_hr,
            avg_pace_s_per_km=round(pace, 1) if pace else None,
            elevation_gain_m=round(elev_gain, 2) if elev_gain else None,
        )

    for i, dp in enumerate(pts):
        if dp["distance_m"] >= next_boundary:
            laps.append(_emit(lap_start_idx, i, _MILE_M))
            lap_start_idx = i
            next_boundary += _MILE_M

    # Partial final lap
    if lap_start_idx < len(pts) - 1:
        remaining = pts[-1]["distance_m"] - pts[lap_start_idx]["distance_m"]
        if remaining >= _MIN_PARTIAL_M:
            laps.append(_emit(lap_start_idx, len(pts) - 1, remaining))

    return laps
```

Then in `parse_fit_file`, replace the `return FitParseResult(...)` block (lines 160–170) with:

```python
    # If the device recorded only one lap (entire run as a single lap),
    # synthesize per-mile splits instead — more useful for pacing analysis.
    if len(laps) == 1:
        laps = _synthesize_mile_laps(datapoints)

    return FitParseResult(
        started_at=started_at,
        distance_m=distance_m,
        duration_s=duration_s,
        elevation_gain_m=elevation_gain_m,
        elevation_loss_m=elevation_loss_m,
        avg_hr=int(avg_hr) if avg_hr is not None else None,
        sport_type=sport_type,
        datapoints=datapoints,
        laps=laps,
    )
```

**Step 4: Run all fit_parser tests**

```bash
cd backend && python3 -m pytest tests/test_fit_parser.py -v
```
Expected: all pass (including existing sample.fit tests if fixture present).

**Step 5: Commit**

```bash
git add backend/app/services/fit_parser.py backend/tests/test_fit_parser.py
git commit -m "feat: synthesize per-mile lap splits for single-lap FIT activities"
```

---

## Task 5: Metrics page backend — Eddington + yearly snapshots

**Files:**
- Modify: `backend/app/services/builder.py:143-149` (rebuild_globals)
- Test: `backend/tests/test_builder.py`

**Context:** Two new static snapshots:
- `/data/static/metrics.json` containing `{eddington: {...}, yearly: {...}}`

Both are computed entirely from the `Activity` table (no DataPoints needed). Add `_rebuild_metrics()` to `builder.py` and call it from `rebuild_globals()`.

**Eddington algorithm:** E is the largest integer where at least E days have distance ≥ E miles. Use a frequency count array: `counts[n]` = number of days with ≥ n miles. Walk backwards from max to find E. History: after processing each day in chronological order, record the date when E increases.

**Step 1: Write failing tests**

Add to `backend/tests/test_builder.py`:

```python
from app.services.builder import _compute_eddington, _compute_yearly


def test_eddington_simple():
    # 5 days each ≥ 5 miles → E=5; 4 days ≥ 6 miles → E=5 still
    daily_miles = {
        "2024-01-01": 5.1,
        "2024-01-02": 5.5,
        "2024-01-03": 6.0,
        "2024-01-04": 6.2,
        "2024-01-05": 5.0,
    }
    result = _compute_eddington(daily_miles)
    assert result["current_e"] == 5
    assert isinstance(result["next_e_gap"], int)
    assert result["next_e_gap"] == 1  # need 1 more day ≥ 6 miles


def test_eddington_zero_when_no_data():
    result = _compute_eddington({})
    assert result["current_e"] == 0
    assert result["next_e_gap"] == 1


def test_eddington_history_grows():
    daily_miles = {f"2024-01-{i:02d}": float(i) for i in range(1, 10)}
    result = _compute_eddington(daily_miles)
    history = result["history"]
    # E should have increased over time
    assert len(history) > 0
    assert history[-1]["e"] == result["current_e"]


def test_yearly_groups_by_week():
    from datetime import date
    # Two activities in the same ISO week, different years
    acts = [
        {"started_at": "2024-01-08T08:00:00", "distance_m": 10000},
        {"started_at": "2023-01-09T08:00:00", "distance_m": 8000},
    ]
    result = _compute_yearly(acts)
    assert "2024" in result["years"]
    assert "2023" in result["years"]
```

**Step 2: Run to verify failure**

```bash
cd backend && python3 -m pytest tests/test_builder.py::test_eddington_simple -v
```
Expected: `ImportError`

**Step 3: Implement `_compute_eddington`, `_compute_yearly`, and `_rebuild_metrics`**

Add to `backend/app/services/builder.py` (before `rebuild_globals`):

```python
_MILE_M = 1609.344


def _compute_eddington(daily_miles: dict[str, float]) -> dict:
    """
    Compute current Eddington number and its growth history.

    daily_miles: {date_iso_str: total_miles_that_day}
    Returns: {current_e, next_e_gap, history: [{date, e}]}
    """
    if not daily_miles:
        return {"current_e": 0, "next_e_gap": 1, "history": []}

    sorted_days = sorted(daily_miles.items())  # chronological
    max_miles = int(max(daily_miles.values())) + 2

    # counts[n] = number of days with distance >= n miles (1-indexed)
    counts = [0] * (max_miles + 1)
    current_e = 0
    history: list[dict] = []

    for day_str, miles in sorted_days:
        n = min(int(miles), max_miles)
        for i in range(1, n + 1):
            counts[i] += 1
        # Advance E as far as possible
        while current_e + 1 <= max_miles and counts[current_e + 1] >= current_e + 1:
            current_e += 1
            history.append({"date": day_str, "e": current_e})

    next_e_gap = (current_e + 1) - counts[current_e + 1] if current_e + 1 <= max_miles else 1
    return {
        "current_e": current_e,
        "next_e_gap": max(0, next_e_gap),
        "history": history,
    }


def _compute_yearly(acts: list[dict]) -> dict:
    """
    Group activity distances by year and ISO week number.
    acts: list of dicts with 'started_at' (ISO str) and 'distance_m'.
    Returns: {years: {str_year: [{week, km}]}}
    """
    from collections import defaultdict
    weekly: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))

    for a in acts:
        started = a["started_at"]
        if isinstance(started, str):
            dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        else:
            dt = started
        year = str(dt.isocalendar()[0])  # ISO year
        week = dt.isocalendar()[1]        # ISO week 1–53
        weekly[year][week] += a["distance_m"] / 1000.0  # km

    years_out = {}
    for year, weeks in sorted(weekly.items()):
        years_out[year] = [
            {"week": w, "km": round(km, 2)}
            for w, km in sorted(weeks.items())
        ]
    return {"years": years_out}


def _rebuild_metrics(session: Session, static_dir: Path) -> None:
    from app.models import Activity

    acts = session.exec(
        select(Activity).order_by(Activity.started_at)
    ).all()

    # Aggregate distance per calendar day (miles)
    from collections import defaultdict
    daily: dict[str, float] = defaultdict(float)
    for a in acts:
        day = a.started_at.date().isoformat()
        daily[day] += a.distance_m / _MILE_M

    act_dicts = [{"started_at": a.started_at, "distance_m": a.distance_m} for a in acts]

    _write_json(static_dir / "metrics.json", {
        "eddington": _compute_eddington(dict(daily)),
        "yearly": _compute_yearly(act_dicts),
    })
```

Then in `rebuild_globals` (line 143–149), add the call:

```python
def rebuild_globals(session: Session, static_dir: Path = STATIC_DIR) -> None:
    """Rebuild activities.json, dashboard.json, goals.json, shoes.json, plans.json, metrics.json."""
    _rebuild_activities(session, static_dir)
    _rebuild_dashboard(session, static_dir)
    _rebuild_goals(session, static_dir)
    _rebuild_shoes(session, static_dir)
    _rebuild_plans(session, static_dir)
    _rebuild_metrics(session, static_dir)   # ← add this line
```

**Step 4: Run builder tests**

```bash
cd backend && python3 -m pytest tests/test_builder.py -v
```
Expected: all pass.

**Step 5: Commit**

```bash
git add backend/app/services/builder.py backend/tests/test_builder.py
git commit -m "feat: add Eddington and yearly mileage to metrics.json static snapshot"
```

---

## Task 6: Rename Fitness → Metrics (frontend)

**Files:**
- Rename: `frontend/src/pages/Fitness.tsx` → `frontend/src/pages/Metrics.tsx`
- Modify: `frontend/src/App.tsx:13,46`

**Step 1: Rename the file**

```bash
mv frontend/src/pages/Fitness.tsx frontend/src/pages/Metrics.tsx
```

**Step 2: Update the page title inside Metrics.tsx**

In `frontend/src/pages/Metrics.tsx`, change line 57:
```tsx
      <h1 className="text-2xl font-bold text-gray-900">Fitness</h1>
```
to:
```tsx
      <h1 className="text-2xl font-bold text-gray-900">Metrics</h1>
```

**Step 3: Update App.tsx**

Replace:
```tsx
import Fitness from "./pages/Fitness";
```
with:
```tsx
import Metrics from "./pages/Metrics";
```

Replace the nav entry:
```tsx
  { to: "/fitness", label: "Fitness" },
```
with:
```tsx
  { to: "/metrics", label: "Metrics" },
```

Replace the route:
```tsx
<Route path="/fitness" element={<Fitness />} />
```
with:
```tsx
<Route path="/metrics" element={<Metrics />} />
```

**Step 4: Commit**

```bash
git add frontend/src/pages/Metrics.tsx frontend/src/App.tsx
git commit -m "feat: rename Fitness page to Metrics"
```

---

## Task 7: Add Eddington and yearly charts to Metrics page

**Files:**
- Modify: `frontend/src/pages/Metrics.tsx`
- Modify: `frontend/src/api/client.ts`

**Step 1: Add getMetrics to client.ts**

In `frontend/src/api/client.ts`, add:

```typescript
export const getMetrics = () => _fetchJson("/static/metrics.json");
```

**Step 2: Add prefetch to App.tsx**

In `frontend/src/App.tsx`, add to the prefetch block:

```typescript
import { getActivities, getStatsSummary, getPersonalBests, getVdot, getMetrics } from "./api/client";
// ...
queryClient.prefetchQuery({ queryKey: ["metrics"], queryFn: getMetrics, staleTime: Infinity });
```

**Step 3: Add Eddington card to Metrics.tsx**

At the top of `Metrics.tsx`, add imports:

```tsx
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { getMetrics } from "../api/client";
```

Add query (with the existing useQuery calls):

```tsx
  const { data: metricsData } = useQuery({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    staleTime: Infinity,
  });

  const eddington = metricsData?.eddington;
  const yearly = metricsData?.yearly;
```

Add the Eddington card (insert before the closing `</div>` of the page):

```tsx
      {/* Eddington Number */}
      {eddington && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">Eddington Number</h2>
          <div className="flex items-start gap-8 flex-wrap">
            <div>
              <div className="text-6xl font-black text-blue-600 leading-none">{eddington.current_e}</div>
              <div className="text-xs text-gray-400 mt-1">
                {eddington.next_e_gap === 0
                  ? `Achieved! Run ${eddington.current_e + 1} mi on ${eddington.current_e + 1} more days for E${eddington.current_e + 1}`
                  : `${eddington.next_e_gap} more run${eddington.next_e_gap === 1 ? "" : "s"} of ≥${eddington.current_e + 1} mi for E${eddington.current_e + 1}`}
              </div>
            </div>
            {eddington.history.length > 1 && (
              <div className="flex-1 min-w-[280px] h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={eddington.history} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(0, 7)} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                    <Tooltip formatter={(v) => [`E${v}`, "Eddington"]} labelFormatter={(l) => l} />
                    <Area type="stepAfter" dataKey="e" stroke="#3b82f6" fill="#dbeafe" strokeWidth={2} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}
```

**Step 4: Add yearly mileage card**

```tsx
      {/* Yearly Mileage Overlay */}
      {yearly?.years && Object.keys(yearly.years).length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">Annual Mileage by Week</h2>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="week" type="number" domain={[1, 53]} tickCount={14} tick={{ fontSize: 10 }} label={{ value: "Week", position: "insideBottomRight", offset: -4, fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} unit=" km" />
                <Tooltip formatter={(v: number, name: string) => [`${v.toFixed(1)} km`, name]} />
                <Legend />
                {Object.entries(yearly.years).map(([year, weeks], i) => {
                  const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];
                  return (
                    <Line
                      key={year}
                      data={weeks as { week: number; km: number }[]}
                      dataKey="km"
                      name={year}
                      stroke={COLORS[i % COLORS.length]}
                      strokeWidth={2}
                      dot={false}
                      type="monotone"
                    />
                  );
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
```

**Step 5: Commit**

```bash
git add frontend/src/pages/Metrics.tsx frontend/src/api/client.ts frontend/src/App.tsx
git commit -m "feat: add Eddington history chart and yearly mileage overlay to Metrics page"
```

---

## Task 8: Weather display on ActivityDetail

**Files:**
- Modify: `frontend/src/pages/ActivityDetail.tsx`

**Context:** The activity data comes from `/static/activity-{id}.json` → `activity` field. The new weather fields are now present on that object. Add a weather row below the existing stat banner if `weather_condition` is non-null.

**Step 1: Add weather condition → emoji map and component**

In `frontend/src/pages/ActivityDetail.tsx`, add after the `RPE_COLORS` constant (around line 33):

```tsx
const WEATHER_EMOJI: Record<string, string> = {
  "Clear": "☀️",
  "Partly cloudy": "⛅",
  "Overcast": "☁️",
  "Fog": "🌫️",
  "Rain": "🌧️",
  "Snow": "❄️",
  "Thunderstorm": "⛈️",
};

function WeatherBanner({ activity }: { activity: Activity }) {
  if (!activity.weather_condition) return null;
  const emoji = WEATHER_EMOJI[activity.weather_condition] ?? "🌡️";
  const temp = activity.weather_temp_c != null ? `${Math.round(activity.weather_temp_c)}°C` : null;
  const feelsLike = activity.weather_feels_like_c != null &&
    Math.abs(activity.weather_feels_like_c - (activity.weather_temp_c ?? 0)) > 2
    ? `feels ${Math.round(activity.weather_feels_like_c)}°` : null;
  const precip = activity.weather_precip_mm != null && activity.weather_precip_mm > 0.1
    ? `${activity.weather_precip_mm.toFixed(1)} mm` : null;
  const cloud = activity.weather_cloud_pct != null ? `${activity.weather_cloud_pct}% cloud` : null;
  const timeOfDay = activity.weather_is_daytime === false ? "🌙 Before/after daylight" : null;

  const parts = [temp, feelsLike, precip, cloud, timeOfDay].filter(Boolean);

  return (
    <div className="flex items-center gap-3 pt-3 mt-3 border-t border-gray-100 text-sm text-gray-600 flex-wrap">
      <span className="text-lg leading-none">{emoji}</span>
      <span className="font-medium text-gray-700">{activity.weather_condition}</span>
      {parts.map((p, i) => (
        <span key={i} className="text-gray-500">{p}</span>
      ))}
    </div>
  );
}
```

**Step 2: Add WeatherBanner to the activity header card**

Find the section in `ActivityDetail.tsx` where the stat cells are rendered (the banner card). At the end of that card's content, before the closing `</div>` of the card, add:

```tsx
              <WeatherBanner activity={act} />
```

**Step 3: Build frontend and verify**

```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: build succeeds with no TypeScript errors.

**Step 4: Commit**

```bash
git add frontend/src/pages/ActivityDetail.tsx
git commit -m "feat: show weather banner on activity detail page"
```

---

## Task 9: Deploy and rebuild static files

**Step 1: Rebuild backend image**

```bash
docker compose build backend
```

**Step 2: Full restart (picks up new image)**

```bash
docker compose down && docker compose up -d
```

**Step 3: Trigger a full static rebuild**

The startup warm-up will rebuild globals (including `metrics.json`). Verify:

```bash
sleep 10 && curl -s http://localhost/static/metrics.json | python3 -m json.tool | head -30
```
Expected: JSON with `eddington.current_e` (integer) and `yearly.years` keys present.

**Step 4: Run all backend tests**

```bash
docker exec runscribe-backend-1 python3 -m pytest /app/tests/ -v 2>&1 | tail -30
```
Expected: all pass.

**Step 5: Final commit**

```bash
git add backend/app/main.py  # if touched
git commit -m "chore: deploy weather, per-mile laps, and metrics page features"
```

---

## Notes for the implementer

- **Open-Meteo rate limits:** 10,000 requests/day free tier. Each upload makes 1 call. Safe for personal use.
- **SQLite migration:** Adding nullable columns with `Optional[...] = None` + `create_all` works without `ALTER TABLE` in SQLite when the table already has rows — SQLModel handles it.
- **Strava sync + weather:** Strava-synced activities that have GPS DataPoints will also get weather on next sync (fetch_weather called in _sync_coros). Strava-only activities without local DataPoints won't get weather.
- **Existing single-lap activities:** Won't get per-mile laps retroactively. A one-off migration script can be added later.
- **Eddington uses miles** (matching the TODO spec). If the user switches to km, the E number will be different — the computation uses a fixed `_MILE_M` constant.
