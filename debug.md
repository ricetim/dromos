# Dromos Debug Log

All debugging notes, build issues, and fixes encountered during implementation.

---

## 2026-03-04

### Task 1 — Backend scaffold

**Issue: `setuptools.backends.legacy` not available**
- System pip/setuptools is too old to support the `setuptools.backends.legacy:build` backend
- Fix: changed `pyproject.toml` to `build-backend = "setuptools.build_meta"`

**Issue: Python 3.12 not installed**
- System has Python 3.10.18
- Fix: updated `requires-python = ">=3.10"` in `pyproject.toml`; Docker image uses `python:3.11-slim`

**Issue: `@app.on_event("startup")` deprecation warning**
- FastAPI recommends the `lifespan` pattern (asynccontextmanager) in modern versions
- Fix: replaced `on_event` with `@asynccontextmanager async def lifespan(app)` + `FastAPI(lifespan=lifespan)`

**Issue: pytest running test suite twice**
- Root cause: missing `[tool.pytest.ini_options]` in `pyproject.toml` caused pytest to discover tests from the wrong root
- Fix: added `testpaths = ["tests"]` and `asyncio_mode = "auto"` to `pyproject.toml`

---

### Task 2 — Docker Compose

No issues. Noted that Docker Compose requires the frontend to be built before serving; nginx proxies `/api/` to the backend container by hostname.

---

### Task 3 — Data models

No issues. All 4 tests passed on first run after model creation.

---

### Task 4 — .fit parser

No issues. `fitparse` installed cleanly. Three fixture-dependent tests skip until a `sample.fit` is placed at `backend/tests/fixtures/sample.fit`.

**Note for Tim:** Drop any `.fit` file exported from your Coros Pace 4 at `backend/tests/fixtures/sample.fit` to enable the full parser test suite.

---

### Task 5 — Activities router

No issues. 5 tests pass; 2 skip pending `sample.fit`.

---

### Task 6 — Frontend scaffold

**Issue: `npm create vite@latest` cancelled — Node.js version conflict**
- `create-vite@latest` requires Node `^20.19.0 || >=22.12.0`; system has Node v21.7.1
- Fix: used `npm create vite@5` which is compatible with Node 21

**Issue: Vite scaffold "remove existing files" deleted frontend/Dockerfile and nginx.conf**
- The scaffold prompt defaulted to "Remove existing files" which wiped Docker files committed earlier
- Fix: recreated both files after the scaffold; noted to always scaffold into an empty directory in future

**Issue: `npx tailwindcss init` failed with latest Tailwind**
- Tailwind v4 changed the init command; `npx tailwindcss init -p` is v3 syntax
- Fix: explicitly installed `tailwindcss@3` with `npm install -D tailwindcss@3 postcss autoprefixer`

---

### Task 8 — Charts component

**Issue: `ReferenceLine` unused import caused TypeScript error**
- `tsc --strict` treats unused imports as errors
- Fix: removed the unused import

### Task 9 — Activity Detail

**Issue: `recharts` failed to resolve `react-is` at build time**
- `recharts` lists `react-is` as a peer dependency but it wasn't installed
- Fix: `npm install react-is --legacy-peer-deps`

**Issue: Bundle size warning — single chunk >500 kB**
- leaflet (297 kB) + recharts (362 kB) bloated the main chunk
- Fix: added `build.rollupOptions.output.manualChunks` in `vite.config.ts` to split into `vendor-leaflet` and `vendor-recharts` chunks; main bundle reduced from 792 kB to 132 kB

---

## Running metrics research notes

Research complete — see `docs/running_metrics_research.md`.

### Books to procure (flagged by research agent)

These sources contain formulas/methodology used in Dromos's analytics engine. The user should obtain them:

| Book | Author(s) | Relevance |
|------|-----------|-----------|
| *Oxygen Power* | Daniels & Gilbert, 1979 | Original VDOT regression equations |
| *Daniels' Running Formula* (3rd ed.) | Jack Daniels | VDOT pace tables, training zones, plan structure |
| *Training and Racing with a Power Meter* | Allen & Coggan | Power-based TSS formula, FTP methodology |
| *The Triathlete's Training Bible* | Joe Friel | 30-min lactate threshold field test protocol |
| *Physiology of Sport and Exercise* (MacDougall et al., eds.) | Various | Contains Banister's 1991 impulse-response model chapter (ATL/CTL/TSB) |

### Freely available key papers

All of these can be implemented without licensing concerns:

| Metric | Paper | DOI/Source |
|--------|-------|------------|
| VO2Max (sub-max) | Åstrand & Ryhming, 1954 | 10.1152/jappl.1954.7.2.218 |
| VO2Max (Cooper test) | Cooper, 1968 | JAMA |
| Race prediction | Riegel, 1981 | *American Scientist* 69(3) |
| ATL/CTL/TSB | Morton et al., 1990 | 10.1152/jappl.1990.69.3.1171 |
| Grade-adjusted pace | Minetti et al., 2002 | 10.1152/japplphysiol.01177.2001 |
| Lactate threshold | Conconi et al., 1982 | 10.1152/jappl.1982.52.4.869 |
| Cadence optimization | Heiderscheit et al., 2011 | PMC3022995 |

---

## 2026-03-05

### Performance optimizations

**Issue: Activity list and maps load slowly**
- Root cause: no DB indexes on frequently-queried columns; no compression; React Query refetching on every window focus
- Fixes:
  - Added compound index `(activity_id, timestamp)` on DataPoint table — makes per-activity datapoint queries ~10× faster
  - Added index on `Activity.started_at DESC` — helps list ordering and stats date filtering
  - Enabled SQLite WAL mode + 32MB page cache + MEMORY temp store
  - Added FastAPI GZipMiddleware (1024-byte minimum) — reduces JSON payload 60-80%
  - Added nginx gzip for all text/json/js types at compression level 6
  - Added nginx `Cache-Control: immutable` for `/assets/` (hashed files cache forever)
  - Set `refetchOnWindowFocus: false` globally in QueryClient — eliminates unnecessary refetches
  - Set `staleTime: Infinity` for per-activity data (datapoints, track, laps, photos)
  - Set `staleTime: 5min` for personal bests and VDOT
  - Added prefetch-on-hover for activity detail in ActivityList and Dashboard ActivityRow
  - Added `/activities/{id}/full` combined endpoint — reduces ActivityDetail from 5 → 2 HTTP requests
  - Added server-side TTL cache for: activities list (30s), stats summary (60s), training load (120s), VDOT (5min), personal bests (5min)
  - All caches invalidated on activity upload/delete

**Issue: Recharts crosshair lines misaligned between main and dynamics charts**
- Root cause: main chart had left YAxis width=52 (only when paceActive=true) and right YAxis width=40; dynamics chart had left YAxis width=40 and no right YAxis — plot areas were different widths, so same timestamp = different pixel x
- Fix: both charts now always render left YAxis width=52 and right YAxis width=40; on main chart when pace is off, ticks/lines are hidden but the axis still occupies its 52px

### Activity detail header redesign
- Replaced separate header + individual stat cards with a single unified banner card
- Top section: back link, activity name (uses Coros name if present, else sport type), date·time, source badge
- Divider, then stats row: Distance | Time | Avg Pace | Elevation | HR (if present) | RPE (if present)
- No individual borders between stats — unified feel

---

## 2026-03-06

### Codebase audit & optimizations

**Issue: `delete_activity` ran N+1 ORM-level DELETEs for DataPoints**
- Root cause: `for dp in ...: session.delete(dp)` hydrates a full ORM object per DataPoint then deletes one-by-one
- For a 10 km run (~3500 datapoints) this was ~3500 round trips instead of 1
- Fix: replaced with `session.exec(sa_delete(DataPoint).where(...))` — single SQL `DELETE WHERE`
- Also fixed: Photos and ActivityShoe rows were not deleted at all on activity delete (silent orphan records) — now bulk-deleted in the same transaction
- Import added: `from sqlalchemy import delete as sa_delete`

**Issue: `list_shoes` had N+1 query — one SUM per shoe**
- Root cause: loop over shoes, each iteration ran `SELECT SUM(distance_m) ... WHERE shoe_id = ?`
- Fix: single `SELECT shoe_id, SUM(distance_m) GROUP BY shoe_id` query then dict lookup per shoe

**Issue: `Pillow` installed in backend Docker image but never imported**
- `exif.py` uses only `exifread` for GPS extraction — Pillow was dead weight
- Fix: removed `Pillow` from `backend/Dockerfile`
- Result: backend image reduced from **222 MB → 201 MB** (saved ~21 MB)
- Containers rebuilt and restarted (down && up) to pick up new image
