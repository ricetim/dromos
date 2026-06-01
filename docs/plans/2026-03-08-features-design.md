# Dromos Feature Design — 2026-03-08

## Features
1. Weather data per activity
2. Per-mile lap splits for single-lap activities
3. Metrics page (rename + Eddington number + yearly mileage overlay)

Strava 429 fix (already deployed) is a prerequisite for all synced data.

---

## 1. Weather Data

### Storage
Seven new nullable columns on the `Activity` table (SQLite migration via SQLModel `create_all`):

| Column | Type | Description |
|---|---|---|
| `weather_temp_c` | float | Actual temperature at run start (°C) |
| `weather_feels_like_c` | float | Apparent temperature (°C) |
| `weather_precip_mm` | float | Precipitation in the run's hour (mm) |
| `weather_cloud_pct` | int | Cloud cover 0–100% |
| `weather_wind_kph` | float | Wind speed (km/h) |
| `weather_condition` | str | Human label derived from WMO code: "Clear", "Partly cloudy", "Overcast", "Rain", "Snow", etc. |
| `weather_is_daytime` | bool | True if `started_at` is between local sunrise and sunset |

### Data Source
Open-Meteo Archive API — free, no API key, supports any historical date.

Endpoint: `https://archive-api.open-meteo.com/v1/archive`

Parameters:
- `latitude`, `longitude` — from first GPS DataPoint of the activity
- `start_date`, `end_date` — the activity date (same value both)
- `hourly=temperature_2m,apparent_temperature,precipitation,cloudcover,windspeed_10m`
- `daily=sunrise,sunset`
- `timezone=auto`

The run's start hour is used to select the correct hourly row. Sunrise/sunset daily values determine `weather_is_daytime`.

### Service
New file: `backend/app/services/weather.py`

```python
def fetch_weather(lat: float, lon: float, started_at: datetime) -> dict | None
```

Returns a dict of the 7 fields, or `None` if the API call fails (non-blocking). Skipped entirely if the activity has no GPS data.

### Trigger Points
- `routers/activities.py` → `upload_fit()` after DataPoints are written and committed
- `routers/sync.py` → `_sync_coros()` after each new activity is committed
- Applied to the activity object immediately, then committed

### Display
ActivityDetail top banner — a new weather row below the existing stat cells:
- Condition label + emoji icon (☀️ ⛅ 🌧️ ❄️)
- Temperature (actual / feels-like)
- Precipitation if > 0
- Cloud cover %
- Sunrise/daytime indicator ("Before sunrise", "After sunset", or omitted if daytime)

Omit the weather row entirely if `weather_condition` is null (activity predates feature or has no GPS).

---

## 2. Per-Mile Lap Splits

### Trigger Condition
In `fit_parser.py`, after laps are parsed from the FIT file: if `len(laps) == 1`, discard the device lap and synthesize mile splits from DataPoints instead.

### Algorithm
Walk DataPoints in timestamp order. Maintain a cursor on accumulated `distance_m`. At each mile boundary (1609.344 m × N):
- Record the boundary timestamp (interpolated between the two surrounding DataPoints)
- Compute `duration_s`, `avg_hr` (mean of HR values in the slice), `elevation_gain_m` (sum of positive altitude deltas)
- Emit a `LapResult` with `lap_number = N`, `distance_m = 1609.344`, computed stats

After the last full mile, if remaining distance > 50 m, emit a final partial lap.

### Storage
Synthetic mile laps are stored in the same `Lap` table with the same schema — no migration needed. The `lap_number` field is 1-indexed (1, 2, 3…) matching device lap convention.

### Scope
Applies only at parse time — newly uploaded or synced activities. Existing single-lap activities are not backfilled automatically (could be added as a one-off migration later if desired).

---

## 3. Metrics Page

### Rename
- Route: `/fitness` → `/metrics`
- Nav label: "Fitness" → "Metrics"
- File: `Fitness.tsx` → `Metrics.tsx`
- Page `<h1>`: "Fitness" → "Metrics"
- `App.tsx` import and route updated accordingly

### Eddington Number

**Definition:** The largest integer E such that you have run at least E miles (or km — we'll use the user's unit preference, defaulting to miles) on at least E separate days.

**Backend endpoint:** `GET /api/stats/eddington` — served via static JSON snapshot (`/static/eddington.json`), rebuilt on every write.

Response shape:
```json
{
  "current_e": 42,
  "next_e_gap": 3,
  "history": [
    {"date": "2022-05-01", "e": 1},
    {"date": "2022-05-08", "e": 2},
    ...
  ]
}
```

- `next_e_gap`: number of additional runs of ≥ (E+1) miles needed to reach E+1
- `history`: one entry per day E increased — not one per run (sparse, chart-friendly)

**Algorithm (O(N log N)):**
1. Aggregate runs by date (sum distance per calendar day)
2. Sort dates by date ascending
3. Walk forward maintaining a sorted frequency array; after each day, binary-search for current E
4. When E increases, append `{date, e}` to history

**Display:**
- Big current E number
- "N more runs of ≥ (E+1) mi needed" sub-label
- `AreaChart` (Recharts) — x: date, y: E value — step interpolation to show flat periods

### Yearly Mileage Overlay

**Backend endpoint:** `GET /api/stats/yearly` — static snapshot (`/static/yearly.json`), rebuilt on every write.

Response shape:
```json
{
  "years": {
    "2023": [{"week": 1, "km": 28.4}, {"week": 2, "km": 35.1}, ...],
    "2024": [...],
    "2025": [...]
  }
}
```

Weeks are ISO week numbers (1–53). Only includes years with at least one run.

**Display:**
- `LineChart` (Recharts) — x: week number (1–53), y: weekly km
- One `<Line>` per year, each a distinct color
- Legend showing year labels
- Tooltip showing all years' values for the hovered week

### Static Snapshot Rebuild
Both new endpoints are added to `services/builder.py` (`bg_rebuild_all` and `bg_rebuild_after_upload`), so they update automatically on every activity write/delete.

---

## Implementation Order
1. Weather service + model migration + upload integration
2. Per-mile lap synthesis in fit_parser
3. Metrics page rename
4. Eddington endpoint + static snapshot + frontend card
5. Yearly mileage endpoint + static snapshot + frontend card
