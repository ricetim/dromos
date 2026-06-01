# Dromos — High-Level Design

## Overview

Dromos is a personal running fitness dashboard for analyzing Coros Pace 4 workout data.
It ingests `.fit` files (directly from Coros, Strava, Runalyze export, or manual upload),
computes Runalyze-style running statistics, and presents them in a rich, interactive web UI —
including maps, charts, GPS-tagged photo pins, gear tracking, goal progress, and auto-generated
training plans from Daniels and Pfitzinger methodologies. The entire application runs as a
Docker container.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Browser (SPA)                         │
│  Dashboard │ Activities │ Activity Detail │ Goals │ Plans   │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP / REST
┌────────────────────────▼────────────────────────────────────┐
│                    Backend API (FastAPI)                     │
│  /activities  /sync  /goals  /gear  /photos  /plans         │
└──────┬──────────────────┬──────────────────────────────────-┘
       │                  │
┌──────▼──────┐  ┌────────▼───────────────────────────────────┐
│  SQLite DB  │  │          Background Sync Service            │
│  (raw +     │  │  Coros poller │ Strava poller │ Scheduled  │
│  processed) │  └────────────────────────────────────────────┘
└─────────────┘

Docker Compose:
  - backend  (FastAPI + APScheduler, port 8000)
  - frontend (Nginx serving Vite build, port 80)
  - volumes: ./data → /data  (SQLite DB + raw .fit files)
```

**Single-machine personal app.** Runs locally or on a personal VPS via Docker Compose.
No auth complexity for single-user local deployment.

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | Python 3.12 + FastAPI | Strong data science ecosystem; fitparse, numpy, pandas |
| Database | SQLite (via SQLModel/SQLAlchemy) | No infra overhead; sufficient for personal data volumes |
| Background jobs | APScheduler (in-process) | Simple periodic sync without Redis/Celery overhead |
| .fit parsing | `fitparse` library | Battle-tested ANT+ FIT format parser |
| Frontend | React 18 + TypeScript + Vite | Fast iteration; rich chart/map ecosystem |
| Maps | Leaflet.js + react-leaflet | Open-source, no API key required |
| Charts | Recharts | React-native, composable, good for time-series drill-down |
| Styling | Tailwind CSS | Utility-first; fast to prototype dashboard layouts |
| Containerisation | Docker + Docker Compose | Single-command startup; portable across machines |

---

## Data Sources

Priority order: Coros API → Strava API → Runalyze export → Manual `.fit` upload.
At least one source is always available; the others layer on additional richness.

### 1. Coros API
Coros offers an official partner API program (application required). There is also an
unofficial reverse-engineered API for bulk `.fit` export.

**Strategy:** Start with manual `.fit` upload to unblock development. Use unofficial Coros API
for historical bulk import. Apply for official API access for ongoing automated sync.

Coros training notes (post-workout journal entries) are available via the API.

### 2. Strava API (Activities + Photos)
If Coros API access is unavailable, Strava can serve as a full activity sync source — all
Coros runs auto-sync to Strava. The Strava API provides both activity streams (time-series GPS,
HR, pace) and activity photos.

Photos may carry EXIF GPS coordinates (from phone camera); these are extracted and used to
place photo markers at the correct location on the activity map.

Activities matched between Coros and Strava by start time (±60 seconds tolerance).

### 3. Runalyze Export
Runalyze allows bulk export of all activities as `.fit` files. This is a one-time historical
import path and requires no API credentials.

### 4. Manual `.fit` Upload
HTTP multipart upload via the API. Always-available fallback.
Files are stored verbatim — **no compression or lossy transformation of raw data.**

---

## Data Model

### `Activity`
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | |
| source | enum | `coros`, `manual_upload` |
| external_id | str | Coros activity ID |
| started_at | datetime | UTC |
| distance_m | float | |
| duration_s | int | Moving time |
| elevation_gain_m | float | |
| avg_hr | int | bpm |
| avg_pace_s_per_km | float | |
| sport_type | enum | `run`, `trail_run`, etc. |
| fit_file_path | str | Path to stored raw .fit file |
| notes | text | Training notes from Coros or user-entered |
| strava_id | str | nullable; for photo lookup |

### `DataPoint` (time-series, per activity)
Raw, full-resolution records from the `.fit` file. **Not aggregated.**

| Field | Type |
|-------|------|
| activity_id | FK |
| timestamp | datetime |
| lat / lon | float |
| distance_m | float |
| speed_m_s | float |
| heart_rate | int |
| cadence | int |
| altitude_m | float |
| power_w | int | nullable |

### `Photo`
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | |
| activity_id | FK | |
| strava_photo_id | str | nullable |
| url | str | |
| captured_at | datetime | nullable |
| lat | float | nullable — EXIF GPS latitude |
| lon | float | nullable — EXIF GPS longitude |

### `Shoe`
| Field | Type |
|-------|------|
| id | UUID |
| name | str |
| brand | str |
| retired | bool |
| notes | text |

### `ActivityShoe`
Many-to-many join between activities and shoes.

### `Goal`
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | |
| type | enum | `weekly_distance`, `monthly_distance`, `annual_distance`, etc. |
| target_value | float | e.g. 50 (km) |
| period_start | date | |
| period_end | date | |
| notes | text | |

### `TrainingPlan`
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | |
| name | str | e.g. "Pfitzinger 18/55 — Boston 2026" |
| source | enum | `daniels`, `pfitzinger` |
| goal_race_date | date | |
| goal_distance | enum | `5k`, `10k`, `half`, `marathon` |
| start_date | date | |
| target_vdot | float | nullable — used by Daniels plans |
| peak_weekly_km | float | nullable — used by Pfitzinger plans |
| notes | text | nullable |

### `PlannedWorkout`
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | |
| training_plan_id | FK | |
| scheduled_date | date | |
| week_number | int | 1-based |
| workout_type | enum | `easy`, `long`, `marathon_pace`, `threshold`, `interval`, `recovery`, `rest` |
| description | text | e.g. "14 miles w/ 8 at marathon pace" |
| target_distance_m | float | nullable |
| target_pace_s_per_km | float | nullable |
| completed_activity_id | FK | nullable — linked when a matching activity is logged |

---

## Feature Modules

### Activity Ingestion
1. Parse `.fit` binary via `fitparse`
2. Extract all `record` messages → `DataPoint` rows (full resolution)
3. Compute derived aggregate fields → populate `Activity` row
4. Trigger Strava photo lookup if `strava_id` is known
5. Persist everything in a single transaction

### Running Statistics (Analytics Engine)
Computed on demand or cached on ingest. Modelled on Runalyze's metric set:

- **Pace zones** — time-in-zone breakdown by HR and pace
- **VDOT** — Jack Daniels formula from race-equivalent performance
- **Training Stress Score (TSS)** — HR-based (hrTSS) and pace-based
- **Acute Training Load (ATL) / Chronic Training Load (CTL) / Training Stress Balance (TSB)**
  — rolling 7-day / 42-day exponential weighted averages
- **Cadence distribution** — histogram
- **Grade-adjusted pace** — Strava GAP formula approximation
- **VO₂max estimate** — from HRmax, resting HR, and max pace segments

All computations operate on the raw `DataPoint` table — no pre-aggregated data needed.

### Interactive Map
- Full-resolution GPS track rendered with react-leaflet polyline
- Colour-coded by pace or HR (user-switchable)
- Click anywhere on the map ↔ highlights the matching point in the charts (bidirectional)
- Segment selection: drag to select a range → show stats for that segment only

### Precision Chart Analysis
- Recharts `LineChart` with brush/zoom component
- X-axis: elapsed time or distance
- Y-axes: pace, HR, elevation, cadence, power (toggleable overlays)
- Selecting a range on any chart syncs the map highlight and shows summary stats for the selection
- **No data downsampling** — renders all DataPoint records

### Photo Gallery & GPS Photo Pins
- Per-activity photo strip below the map
- Photos pulled from Strava at sync time and URL-cached
- Lightbox on click
- Photos with EXIF GPS coordinates are also rendered as map markers at their capture location
- Clicking a photo marker opens the photo in a lightbox

### Gear Tracking
- Assign shoes to an activity at upload or edit time
- Dashboard widget: distance per shoe, estimated remaining life vs. retirement threshold
- Retirement flag and replacement workflow

### Goals
- Create goals with a type, target, and date range
- Progress computed by summing activity metrics within the goal period
- Dashboard summary card shows all active goals with progress bars

### Training Plans
Generate structured multi-week training plans from two methodologies:

**Jack Daniels (Running Formula)**
- Input: goal race (distance + date), current VDOT (derived from recent race or estimated)
- Output: daily workouts with prescribed type (E/M/T/I/R) and distance, plus target paces
  computed from the VDOT tables (Easy, Marathon, Threshold, Interval, Repetition paces)
- Plans range from 5K to marathon; typically 12–24 weeks

**Pete Pfitzinger (Advanced Marathoning)**
- Input: goal marathon date, peak weekly mileage tier (55 / 70 / 85 mpw)
- Output: structured 18-week plan with long runs, medium-long runs, marathon pace workouts,
  lactate threshold runs, and recovery days
- Plan templates are encoded as structured data (week × day matrix)

**Compliance tracking:** Each `PlannedWorkout` can be linked to a completed `Activity` by
matching date and approximate distance (±20%). The plans page shows a calendar view with
completed workouts highlighted in green and missed ones in red.

---

## API Endpoints (Backend)

```
POST   /api/activities/upload          # Manual .fit upload
GET    /api/activities                 # Paginated activity list
GET    /api/activities/{id}            # Activity detail + stats
GET    /api/activities/{id}/datapoints # Full-resolution time-series
GET    /api/activities/{id}/photos     # Photos for activity
PATCH  /api/activities/{id}            # Edit notes, shoe assignment

GET    /api/sync/status                # Last sync time, errors
POST   /api/sync/trigger               # Manual sync from Coros

GET    /api/shoes                      # All shoes
POST   /api/shoes                      # Create shoe
PATCH  /api/shoes/{id}                 # Update / retire

GET    /api/goals                      # All goals with progress
POST   /api/goals                      # Create goal
DELETE /api/goals/{id}

GET    /api/stats/summary              # ATL/CTL/TSB, weekly totals

GET    /api/plans                      # All training plans
POST   /api/plans                      # Generate new plan (daniels or pfitzinger)
GET    /api/plans/{id}                 # Plan detail with all planned workouts
DELETE /api/plans/{id}
GET    /api/plans/{id}/workouts        # Planned workouts, with compliance status
PATCH  /api/plans/{id}/workouts/{wid}  # Manually link/unlink a completed activity
```

---

## Frontend Pages

| Route | Description |
|-------|-------------|
| `/` | Dashboard: recent runs, ATL/CTL/TSB chart, goal progress, shoe mileage |
| `/activities` | Scrollable activity log with filters (date, sport, distance) |
| `/activities/:id` | Activity detail: map + GPS photo pins, charts, photo gallery, stats, notes, gear |
| `/gear` | Shoe roster and mileage tracker |
| `/goals` | Goal list and creation |
| `/plans` | Training plan list and creation |
| `/plans/:id` | Calendar view of plan with compliance status |

---

## Open Questions

1. **Coros API access** — apply for official partner access or use the unofficial export tool for historical data? Start with manual upload to unblock development.
2. **Strava as full activity source** — if Coros runs auto-sync to Strava, Strava streams can substitute for `.fit` data. Requires confirming all workouts are synced and streams have full resolution.
3. **Hosting** — local-only (no auth needed) or self-hosted VPS (add simple API key or basic auth)?
4. **Map tile provider** — OpenStreetMap free tiles are sufficient; consider Mapbox for terrain/satellite view.
5. **EXIF GPS extraction** — Strava photo API returns URLs but may not include EXIF. May need to download the photo and extract EXIF client-side or server-side with `Pillow`/`exifread`.
6. **Pfitzinger plan encoding** — plan schedules are copyright; need to encode from the book manually as structured data, or use a freely available equivalent.

---

## Development Phases

| Phase | Deliverables |
|-------|-------------|
| 1 — Core Ingest | `.fit` parser, DataPoint storage, Activity list API, minimal React shell, Docker Compose |
| 2 — Activity Detail | Map, GPS photo pins, charts (pace/HR/elevation), precision range selection |
| 3 — Analytics | Stats engine (VDOT, TSS, ATL/CTL), dashboard summary |
| 4 — Photos & Strava | Strava OAuth, photo + activity sync, EXIF GPS extraction |
| 5 — Gear & Goals | Shoe tracking, goal creation and progress |
| 6 — Training Plans | Daniels and Pfitzinger plan generators, compliance calendar |
| 7 — Coros Sync | Automated sync via Coros API (pending API access approval) |
