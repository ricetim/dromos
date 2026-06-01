# Shoe-Link Cleanup & Deduplication Plan

**Date:** 2026-05-20
**Goal:** Fix the duplicate-`ActivityShoe`-link bug that causes the wrong shoe to appear on activity-detail pages and double-counts mileage on the gear page.

## The Bug

User-reported symptom: activity 119 shows "Altra Torin 8" on its detail page, but the filter `?shoe=4` (Altra FWD VIA 2) also includes activity 119.

Inspecting the prod DB confirms: 8 activities have two `ActivityShoe` rows pointing at *different* shoes.

```
activity_id | n | shoe_ids
   52       | 2 | 3,1
   95       | 2 | 1,4
   98       | 2 | 3,4
  117       | 2 | 3,4
  118       | 2 | 3,4
  119       | 2 | 3,4   ← reported
  121       | 2 | 3,4
  122       | 2 | 3,4
```

There are no exact-duplicate pairs (no `(act, shoe)` row twice) — every duplicate is a *different* shoe for the same activity.

## Root Cause

`backend/app/routers/sync.py:233-250` (Strava sync, ActivityShoe linking step):

```python
for gear_id, act_ids in gear_map.items():
    shoe = session.exec(select(Shoe).where(Shoe.strava_gear_id == gear_id)).first()
    if not shoe:
        continue
    for act_id in act_ids:
        already = session.exec(
            select(ActivityShoe)
            .where(ActivityShoe.activity_id == act_id)
            .where(ActivityShoe.shoe_id == shoe.id)
        ).first()
        if not already:
            session.add(ActivityShoe(activity_id=act_id, shoe_id=shoe.id))
```

The "already" check looks for `(activity_id, shoe_id)` — but if the activity's gear on Strava changes (you swap shoes), Strava sends a *different* `gear_id` next run. The check doesn't match, so a second `ActivityShoe` row is inserted for the same activity pointing at the new shoe. The original link is never removed.

The other write paths are correct:
- `PATCH /activities/{id}/shoe` (`activities.py:368-372`) deletes then inserts.
- Manual upload doesn't create links at all.

## Knock-on Effects

1. **Detail view picks wrong shoe.** `ActivityDetail.tsx:385`: `shoes[0].id` — picks whichever row sorted first, often the stale one.
2. **Gear-page mileage is double-counted.** `_rebuild_shoes` (`builder.py:320+`) does `SELECT ... FROM activity_shoe JOIN activity` and sums distance per row. Duplicate-linked activities get their distance credited to *both* shoes.
3. **Shoe timeline chart is wrong** for the same reason.

## Design Decision: 1:1 Not M2M

The schema models `ActivityShoe` as many-to-many, but every code path uses it as one-to-one (one shoe per activity). The right fix is to enforce that at the data layer and stop pretending it's M2M.

**Resolution rule for existing duplicates: keep the newest link** (highest `ActivityShoe.id`). The newest link reflects the most recent Strava gear assignment, which is most likely what the user intended. For the 8 dirty rows, this resolves to the recent shoe (FWD VIA 2 in most cases).

This is not a perfect rule — but it's a one-shot cleanup of 8 rows, and a manual review override stays available via the existing `PATCH /activities/{id}/shoe` endpoint after the fact.

## Implementation

### Task 1 — Fix Strava sync to replace, not append

**File:** `backend/app/routers/sync.py:233-250`

Before linking a `(act_id, shoe_id)` pair, delete any other `ActivityShoe` rows for that `act_id`. Skip the insert if the existing row already points at the correct shoe.

```python
for gear_id, act_ids in gear_map.items():
    shoe = session.exec(select(Shoe).where(Shoe.strava_gear_id == gear_id)).first()
    if not shoe:
        continue
    for act_id in act_ids:
        existing = session.exec(
            select(ActivityShoe).where(ActivityShoe.activity_id == act_id)
        ).all()
        if any(link.shoe_id == shoe.id for link in existing):
            continue  # already correct
        for link in existing:
            session.delete(link)
        session.add(ActivityShoe(activity_id=act_id, shoe_id=shoe.id))
        links_created += 1
```

- [ ] Update `sync.py:233-250` per above
- [ ] Add a test: `tests/test_sync.py` (or wherever sync tests live) — sync once with gear A, sync again with gear B for the same activity, assert exactly one link remains pointing at B

### Task 2 — Add a uniqueness constraint at the DB layer

**Files:** `backend/app/models.py:83`, `backend/app/database.py`

Make `ActivityShoe.activity_id` unique. Belt-and-suspenders against future leaks.

```python
class ActivityShoe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activity.id", unique=True, index=True)
    shoe_id: int = Field(foreign_key="shoe.id", index=True)
    ...
```

SQLModel `create_all` won't add the constraint to an existing table. Add a manual migration in `database.py:create_db_and_tables`:

```python
_create_unique_index(conn, "activityshoe", "ix_activityshoe_activity_id_unique", "activity_id")
```

…where `_create_unique_index` is a new helper that issues `CREATE UNIQUE INDEX IF NOT EXISTS ix_name ON table(column)` and swallows the error if the index already exists. (Cleaner than `ALTER TABLE` since SQLite doesn't support adding constraints in-place.)

The unique index will fail to apply if duplicates still exist, so Task 3 must run *before* the new image deploys, or the migration must dedupe before adding the index.

- [ ] Add `unique=True` to the field
- [ ] Add `_create_unique_index` helper to `database.py`
- [ ] Call it from `create_db_and_tables`

### Task 3 — One-shot dedupe in startup

**File:** `backend/app/main.py:_startup_rebuild`

Run once on startup to clean up the 8 stale rows. Keep the latest `ActivityShoe.id` per activity, delete the rest.

```python
# Dedupe ActivityShoe — see plan 2026-05-20 for context
session.exec(text("""
    DELETE FROM activityshoe
    WHERE id NOT IN (
      SELECT MAX(id) FROM activityshoe GROUP BY activity_id
    )
"""))
session.commit()
```

This runs every startup but is idempotent — once cleaned, no rows match the delete.

Ordering inside `_startup_rebuild`:
1. (existing) plans.json cleanup
2. **(new) ActivityShoe dedupe**
3. (existing) check if activities.json missing → full rebuild
4. (existing) otherwise → refresh globals → warm cache

Globals rebuild after dedupe so `shoes.json` reflects the corrected totals.

- [ ] Add dedupe `DELETE` before the `if not (STATIC_DIR / "activities.json").exists():` branch
- [ ] Confirm it runs *before* `rebuild_globals` so the static JSON is correct
- [ ] Verify `_create_unique_index` runs *after* dedupe (it does — `create_db_and_tables` runs from `lifespan`, before the `_startup_rebuild` thread starts… wait, this is wrong, see verification)

> **Ordering subtlety:** `create_db_and_tables()` is called synchronously in `lifespan` *before* the `_startup_rebuild` thread starts. So the unique index would try to apply *before* the dedupe runs, and fail on the duplicate rows. Two options:
>
> - **A. Move `_create_unique_index` to run after dedupe**, inside `_startup_rebuild`.
> - **B. Dedupe inline in `create_db_and_tables`**, before `_create_unique_index`.
>
> Option B keeps schema-setup all in one place. Recommended.

### Task 4 — Singular `shoe` in frontend types (optional cleanup)

Once the DB enforces uniqueness, the frontend can stop pretending there's a list. `ActivityDetail.tsx:350` does `(full as any)?.shoes` — change to a single field. Not blocking; cosmetic.

- [ ] (optional) Backend `_rebuild_activities` writes `shoe_name` (singular) instead of `shoe_names` array
- [ ] (optional) `ActivityDetail.tsx`, `ActivityList.tsx`, `CalendarView.tsx` use the singular field
- [ ] (optional) Remove `shoes` array from `/activities/{id}/full` response

Skip if you'd rather not churn the UI for cosmetic gain.

## Verification

After the new image is deployed on coruscant:

1. `sqlite3 /home/tim/.docker_config/dromos/dromos.db "SELECT activity_id, COUNT(*) FROM activityshoe GROUP BY activity_id HAVING COUNT(*) > 1"` — should return zero rows.
2. Open https://dromos.timothyrice.org/activities/119 — detail view shows the *current* shoe (FWD VIA 2).
3. Open the Gear page — Altra Torin 8 total km should drop (lost the 8 double-counted activities); FWD VIA 2 total should be unchanged (it was already getting credit for them).
4. Re-run Strava sync, then re-run again with a different gear assignment in Strava on a test activity. Confirm only one `ActivityShoe` row exists for that activity.

## Out of Scope

- Backfilling historical shoe assignments where Strava has no record (no source of truth available).
- Letting a single activity be linked to multiple shoes legitimately (split runs, etc.). The app doesn't support this and the user hasn't asked for it.
- Reparsing FIT files to recover any embedded gear metadata.
