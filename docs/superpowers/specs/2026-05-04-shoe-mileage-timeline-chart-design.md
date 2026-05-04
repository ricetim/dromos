# Shoe Mileage Timeline Chart — Design

**Date:** 2026-05-04
**Goal:** Add a cumulative-mileage line chart to the Gear page showing every shoe's lifetime wear over time, scoped by a year dropdown.

## Summary

Each shoe gets one line on a chart that climbs as miles accumulate. Active shoes are solid; retired shoes are dashed and faded. A year dropdown filters the visible time window — selecting a year shows that year's range with shoes entering at their carry-over cumulative total (lifetime values, scoped window). All chart data is precomputed server-side and served as static JSON.

## Architecture

The site is static-first: nginx serves precomputed JSON from `/static/`, and only mutations (POST/PATCH/DELETE) hit FastAPI. All derived/computed data must follow this pattern. The shoe timeline is no exception — it is precomputed in `_rebuild_shoes` and written to `shoes.json` on every mutation that affects shoe-to-activity links.

## Data Shape

`shoes.json` gains two fields per shoe:

```ts
timeline: { date: string; cumulative_km: number }[]   // one entry per linked activity, ascending by date
years: number[]                                        // distinct years that contain at least one activity for this shoe
```

`timeline[i].cumulative_km` is the lifetime running total *after* activity `i` is added. The frontend uses these directly — no client-side aggregation.

The year-dropdown options are the union of every shoe's `years` plus an `"All time"` default, sorted descending.

## Backend Changes

**File:** `backend/app/services/builder.py`

Extend `_rebuild_shoes` to compute timelines:

1. Single query: `SELECT activity_shoe.shoe_id, activity.started_at, activity.distance_m FROM activity_shoe JOIN activity ON ... ORDER BY shoe_id, activity.started_at ASC`
2. Walk rows, tracking running cumulative per shoe; emit `{date: started_at.date().isoformat(), cumulative_km: round(total_m / 1000, 1)}` entries.
3. Collect distinct years per shoe (from each `started_at.year`).
4. Add `timeline` and `years` arrays to each shoe's JSON output.

The existing `total_distance_km` field stays — it's the same as `timeline[-1].cumulative_km` and is used elsewhere.

**Triggers (already in place):** `_rebuild_shoes` is called from `bg_rebuild_after_upload`, `bg_rebuild_after_delete`, `bg_rebuild_after_activity_update`, and `bg_rebuild_globals`. These cover activity uploads/deletes, shoe assignment changes (`PATCH /activities/{id}/shoe`), and activity updates. No new wiring is needed.

## Frontend Changes

**File:** `frontend/src/pages/Gear.tsx`

1. **Type updates:** Extend the local `Shoe` interface with `timeline: { date: string; cumulative_km: number }[]` and `years: number[]`.

2. **Year dropdown state:** `useState<"all" | number>("all")`. Options come from the union of all `shoe.years` plus `"All time"`, sorted descending.

3. **New `<ShoeTimelineChart>` component** using Recharts `LineChart`:
   - One `<Line>` per shoe, color-coded from `CHART_COLORS` in `frontend/src/config.ts`.
   - Retired shoes: `strokeDasharray="4 2"` and `strokeOpacity={0.5}`.
   - X-axis: time (date string), formatted with `formatDateMonthDay` for year-scoped views and `formatDateShort` for "All time".
   - Y-axis: cumulative distance (km or mi via `fmtShoe` from `useUnits`).
   - Horizontal `<ReferenceLine>` at each shoe's `retirement_threshold_km` (only in "All time" view — not meaningful within a single year).
   - Tooltip on hover shows shoe name + cumulative distance.

4. **Year-scoping logic:** When a year is selected, filter each shoe's timeline to entries with `date` in `[YYYY-01-01, YYYY-12-31]`. If a shoe has any earlier entries, prepend a synthetic point at `YYYY-01-01` with the last pre-year `cumulative_km`, so the line enters the chart at the correct height. Skip shoes entirely if they have no entries in or before the selected year.

5. **Layout:** Chart sits above the active-shoes list, with the year dropdown in the top-right of the page header (next to the existing "+ Add Shoe" button).

## YAGNI Exclusions

- No interactivity beyond hover tooltip and year filter.
- No per-shoe show/hide toggles.
- No animations beyond Recharts defaults.
- No "active only" / "retired only" filter — visual distinction (dashed + faded) is enough.

## Files Touched

- `backend/app/services/builder.py` — extend `_rebuild_shoes` (~15 LoC)
- `frontend/src/pages/Gear.tsx` — add chart component, year dropdown, type updates (~80 LoC)

## Acceptance

- [ ] `shoes.json` contains `timeline` and `years` for every shoe
- [ ] Timeline rebuilds on activity upload, delete, and shoe assignment change
- [ ] Chart renders one line per shoe; retired shoes are dashed and faded
- [ ] Year dropdown defaults to "All time" and shows distinct years from any shoe's history
- [ ] Year-scoped view shows shoes entering at their carry-over cumulative total
- [ ] Retirement-threshold reference lines appear only in "All time" view
- [ ] Tooltip shows shoe name and cumulative distance
- [ ] Units toggle (mi/km) works on the chart's Y-axis
