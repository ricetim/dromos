THIS FILE CONTAINS A RUNNING LOG OF PROJECT REQUIREMENTS, ORGANIZED BY DATE OF ADDITION.

# 2023-03-04
project will be a running fitness dashboard, showcasing workouts and analysis of the
import .fit files from coros pace 4
	can it come directly from coros, or does it need to come from strava? does coros have an api?
	if data cannot come from coros, determine if it can come from strava via their api, or even from runalyze.
	can it import the training notes from coros that I make after every workout?
display a log of previous runs, with personal notes and stats
compute running statistics similar to what runalyze does
	old runalyze git repo can be found here: https://github.com/runalyze
	current runalyze docs here: https://runalyze.com/
allow for precision analysis of small portions of the workout. Don't compress data!
import and showcase photos from the run (likely from strava) if they exist
track gear usage (shoes)
show an interactive map of the run
allow for goal setting (mileage totals, etc) and tracking of those goals
this should run as a docker container
photos with gps data should be shown on the map for a workout 
should include the creation of training plans for popular sources like daniels and pfitzinger
research how running metrics are calculated from first principles
	metrics of interest: VO2Max, race time predictions (5k/10k/half/marathon), training stress, lactate threshold, running economy
	source research papers where possible; note any book sources so they can be procured
Add ability to create workouts based on the Daniels white, red, blue, and gold training plans detailed in his running formula book
review this webpage for information:  https://fellrnr.com/wiki/Modeling_Human_Performance#The_Banister_Formula

# 2026-03-05
Performance optimizations:
  - Activities and maps load slowly — need static-site-like performance
  - Cache all expensive server-side data (personal bests, stats, activity list, VDOT, training load)
  - Avoid unnecessary HTTP refetches on the frontend
  - Pre-fetch activity detail data on hover in activity lists

Activity detail header should be a single unified banner card (not separate title + stat cards)
  - One card: activity name/date left, stats row right, separated by a divider

Crosshair vertical lines on analysis and dynamics charts must be at the same timestamp position
  - Charts must have identically sized X-axis plot areas

Personal bests: show top 20 historical best efforts per distance (not just the single best)

# 2026-03-06

## Strava gear (shoe) integration research
Strava API exposes shoe data in two places:
- `GET /api/v3/athlete` → `shoes[]` array: id, name, brand_name, distance (metres, lifetime), retired
- `GET /api/v3/activities/{id}` → `gear_id` field: links a specific activity to a gear item

Implementation plan when ready:
1. Add `strava_gear_id` field to `Shoe` model (e.g. "g12345678") to deduplicate syncs
2. On each Strava sync: fetch `/api/v3/athlete`, upsert shoes by strava_gear_id
3. For each activity with a `strava_id`, fetch activity detail to get `gear_id`, then create/update ActivityShoe link
4. Strava gear distance is cumulative lifetime — don't use it as source of truth; compute from our own DataPoints

## Historical Strava import (2026-03-08, completed)
- Added `fetch_activity_laps` to strava service
- Sync now uses `after=0` to fetch full Strava history (removed earliest-local-activity bound)
- Filters to run types only: Run, VirtualRun, TrailRun
- Imported 40 pre-Coros activities (Sept 5 – Dec 24, 2025) via manual script
- Annual mileage chart now shows 2025 data from week 36 onward
- Weather not backfilled for historical imports (Open-Meteo historical API could do this)

## Feature backlog (from codebase audit 2026-03-06)
Priority order (most impactful first):
1. Strava shoe auto-import (see above)
2. Weekly volume bar chart on Dashboard — 12-week mileage history
3. Heart rate zone breakdown per activity — time-in-zone chart
4. Grade-adjusted pace (GAP) on activity detail — formula already in design.md
5. Gradient-colored GPS track — polyline colored by pace or HR (design mentions, not yet implemented)
6. Activity best efforts table — within activity view, compare that run's segments vs all-time PBs
7. Dark mode
8. Export activity as GPX
9. Training load forecast — project CTL/ATL forward based on planned workouts
10. Multi-activity comparison — overlay two runs on same chart/map

## Docker image size notes
- Backend: 201 MB (was 222 MB; saved 21 MB by removing unused Pillow)
- Frontend: 63.1 MB (nginx:alpine + Vite dist — already near minimum)
- Further backend savings possible: switch `uvicorn[standard]` → `uvicorn` (~5-10 MB) if websockets not needed
