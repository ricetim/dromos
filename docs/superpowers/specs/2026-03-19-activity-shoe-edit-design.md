# Activity Shoe Edit — Design Spec

**Date:** 2026-03-19

## Summary

Add the ability to assign or change the shoe on an individual activity from the ActivityDetail page. One shoe per activity is enforced at the API level. Selection auto-saves via a dropdown.

## Constraints

- Maximum one shoe per activity (enforced server-side)
- Auto-save on dropdown change (no explicit save button)
- Only active (non-retired) shoes appear as options

## Backend

### New Endpoint

`PATCH /api/activities/{activity_id}/shoe`

**Request body:** `{"shoe_id": int | null}`

**Behavior:**
1. Delete all existing `ActivityShoe` rows for the activity
2. If `shoe_id` is non-null, insert a new `ActivityShoe` row
3. Trigger background rebuilds:
   - `bg_rebuild_activity(activity_id)` → regenerates `activity-{id}.json`
   - `bg_rebuild_globals()` → regenerates `activities.json` and `shoes.json` (distances change)
4. Invalidate TTL caches: activities list, training load

**Location:** `backend/app/routers/activities.py`

No schema changes. Reuses existing `ActivityShoe` model and builder queries.

## Frontend

### ActivityDetail.tsx

Replace the read-only shoe display (shoe emoji + names) with a `<select>` dropdown:

- **Options:** "No shoe" (value = `""`) + all active shoes from the existing `["shoes"]` query
- **Pre-selected:** current shoe if one is assigned, otherwise "No shoe"
- **On change:**
  - Call `PATCH /api/activities/{id}/shoe` with `{shoe_id: int | null}`
  - Invalidate query cache keys: `["activity-full", id]`, `["shoes"]`, `["activities"]`
- **Loading state:** dropdown disabled while mutation is in-flight
- **Error state:** brief inline error message next to dropdown on failure

### api/client.ts

Add `updateActivityShoe(activityId, shoeId)` → `PATCH /api/activities/{id}/shoe`

## Files Changed

- `backend/app/routers/activities.py` — new endpoint
- `frontend/src/api/client.ts` — new mutation function
- `frontend/src/pages/ActivityDetail.tsx` — replace shoe display with dropdown
