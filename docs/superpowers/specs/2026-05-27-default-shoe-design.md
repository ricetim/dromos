# Default Shoe (and removal of Strava shoe sync) — Design

**Date:** 2026-05-27
**Status:** Approved
**Author:** brainstorming session

## Problem

Today, shoes are linked to activities only via Strava's gear field — synced inside `_sync_strava_activities`. This requires Strava bookkeeping outside Domos, and it doesn't help with activities that arrive from Coros sync or direct `.fit` upload. We want shoe attribution to be a first-class, in-app concern with a simple default-shoe model, and to retire the Strava-driven path entirely.

## Goals

1. Remove the Strava shoe-sync logic and its supporting Strava-specific schema.
2. Let the user pick a single **default shoe** on the Gear page.
3. New activities from any source (Coros, Strava-streams, manual upload) are stamped with the default shoe at ingest time, if a default is set.
4. The existing per-activity override (`PATCH /activities/{id}/shoe`) continues to work.
5. Retiring a shoe automatically clears it as default.
6. Preserve all existing `ActivityShoe` history — no destructive migration.

## Non-goals

- No retroactive backfill of past activities when the default is first set or changed.
- No multi-shoe-per-activity support (DB unique index already enforces one).
- No `ON DELETE` FK constraint at SQL level (handled in Python via retirement hook).

## Behavior model

**Stamp-at-ingest.** When an activity is ingested, the current default shoe (if any) is written as an `ActivityShoe` row in the same transaction. Changing the default later does **not** repaint old activities. This preserves the historical record "this run used shoe A on the day it arrived."

**Default storage.** A nullable `default_shoe_id` column on the existing `UserProfile` singleton (`models.py:92`). `null` means no default — activities from then on get no shoe link unless manually assigned.

**Retire-auto-clears.** When a shoe is patched to `retired=True`, if it is the current default, `UserProfile.default_shoe_id` is cleared in the same transaction. Re-activating a retired shoe does **not** re-promote it; the user must re-pick.

**Validation.** `PATCH /api/profile` rejects setting `default_shoe_id` to a retired or non-existent shoe with HTTP 400. The UI hides the star control on retired shoes as an affordance, but the server is the source of truth.

## Schema changes

`UserProfile` — add column:
```python
default_shoe_id: Optional[int] = Field(default=None, foreign_key="shoe.id")
```

`Shoe` — drop column `strava_gear_id`.

Migration, inside `init_db()` in `database.py`:
- `_add_column(conn, "userprofile", "default_shoe_id", "INTEGER")` (idempotent, additive).
- `ALTER TABLE shoe DROP COLUMN strava_gear_id` wrapped in try/except for idempotency. SQLite 3.35+ required; both dev (3.10's bundled 3.37) and the `python:3.11-slim` Docker base satisfy this.

No Alembic, no FK constraint at the SQL level — matches project convention. Shoes are never hard-deleted (only retired), so a dangling default-id is not a practical risk; the read path treats missing shoes as "no default."

## Backend changes

**New helper** `backend/app/services/shoe_default.py`:
```python
def stamp_default_shoe(session: Session, activity_id: int) -> None:
    profile = session.get(UserProfile, 1)
    if profile and profile.default_shoe_id:
        session.add(ActivityShoe(
            activity_id=activity_id,
            shoe_id=profile.default_shoe_id,
        ))
```

**Call sites** — invoke after `session.flush()` (so `activity.id` is available), before the surrounding `session.commit()`:
1. `_sync_coros` in `sync.py:322` (Coros ingest).
2. The unmatched-Strava-import loop in `sync.py:150` (Strava-stream import).
3. The manual `.fit` upload path in `activities.py` (`POST /api/activities`).

**Remove Strava shoe sync** in `sync.py`:
- Delete sections 3 & 4 (lines ~198–254): athlete shoe upsert, gear-id fallback fetch, ActivityShoe linking.
- Remove `fetch_athlete` and `fetch_gear` from the import line at the top.
- Remove `shoes_synced` and `shoe_links_created` keys from the `_last_sync` payload.
- If `fetch_athlete` / `fetch_gear` are not referenced elsewhere, also delete them from `services/strava.py`.

**`PATCH /api/profile`** (`profile.py:23`): extend allowlist to include `default_shoe_id`. Before `setattr`, validate: if value is non-null, look up the shoe and reject with 400 if missing or `retired=True`.

**`PATCH /api/shoes/{shoe_id}`** (`shoes.py:36`): after applying patch fields, if the shoe is now retired and matches `UserProfile.default_shoe_id`, clear it in the same transaction. Existing `bg_rebuild_globals` task already covers the static refresh.

**`_rebuild_shoes`** (`builder.py:473`): read `UserProfile.default_shoe_id` once at the top, emit `is_default: bool` on each shoe row in `shoes.json`. Frontend consumes directly — no client-side ID comparison.

## Frontend changes

**`frontend/src/pages/Gear.tsx`:**

- Extend the local `Shoe` interface with `is_default: boolean`.
- Add `setDefaultMutation` that calls `PATCH /api/profile` with `{default_shoe_id: id | null}` and invalidates the `["shoes"]` query.
- In the active-shoes list (`Gear.tsx:309-331`), add a star button as the **leftmost** element of each row:
  - Filled gold star (`★`) when `shoe.is_default`; outlined gray star (`☆`) otherwise.
  - `onClick`: if filled, mutate `null` (clear); if outlined, mutate `shoe.id`.
  - `aria-label`: `"Default shoe"` (filled) or `"Set as default"` (outlined).
- Retired shoes (`Gear.tsx:344-359`) get **no** star control — visually signals that retired shoes can't be default.
- Optional: add a `setDefaultShoe(id)` helper in `frontend/src/api/client.ts` for symmetry with `updateActivityShoe`.

## Static content

`/static/shoes.json` gains an `is_default: bool` per shoe object. No top-level shape change — keeps the response a plain array, which is what existing consumers expect.

No new static file. The `/api/profile` GET endpoint remains the authoritative read for `default_shoe_id` if any future feature needs the raw value.

## Migration & rollout

Single PR, sequential within:
1. Schema migration (additive + drop).
2. Backend logic (helper, three call sites, profile validation, retirement hook, builder).
3. Strava sync excision.
4. Frontend (star button, mutation, type).
5. Manual smoke: Strava sync → confirm `_last_sync` healthy & no shoe changes; pick default; upload `.fit`; verify default on Activity Detail.

**Rollback**: `git revert` restores the old sync. The added `default_shoe_id` column is harmless if unused. The dropped `strava_gear_id` would need to be re-added (`_add_column`) for a full rollback, since SQLite cannot un-drop a column without table rebuild. Documented as a one-line manual step.

## Tests (~6 new, in `backend/tests/`)

- `test_default_shoe_stamped_on_coros_ingest` — seed default, run `_sync_coros` against mock, assert `ActivityShoe` link exists.
- `test_default_shoe_stamped_on_manual_upload` — POST `.fit`, assert link.
- `test_no_default_no_link` — default = None, ingest, assert zero links.
- `test_retire_default_clears_profile` — set default, PATCH `retired=True`, assert `default_shoe_id is None`.
- `test_patch_profile_rejects_retired_default` — try to set retired shoe as default, expect 400.
- `test_strava_sync_no_longer_touches_shoes` — run sync with mock gear payload, assert `Shoe` / `ActivityShoe` row counts unchanged.

## Risk hot-spots (for code review)

- **Stamp ordering.** `stamp_default_shoe` adds an `ActivityShoe` to the session; the caller must commit. Each call site must follow `flush → stamp → commit` so the unique index on `activityshoe.activity_id` doesn't trip on partial state. The Strava-streams loop in particular commits at line 196 *after* the loop body; stamping must happen inside the loop body.
- **Vestigial `strava_gear_id`.** The drop is one-way on SQLite. We could defer it for one release. Recommendation: drop now — "vestigial column" rot is real.
- **Concurrent retire + sync.** If a sync is in flight when the user retires the default, the helper might read the now-cleared profile after the retire commits, or the old value before. Worst case: one stamped activity for a just-retired shoe. Personal-app scale, not worth locking; document and move on.

## Open questions

None — all questions resolved during brainstorming. Question/answer log:

- Q1: behavior on default change — A: **stamp-at-ingest**, no retroactive repaint.
- Q2: fate of existing Strava-imported shoe data — A: **keep links, drop column**.
- Q3: UX for picking default — A: **star icon per active shoe row**; storage on `UserProfile.default_shoe_id`.
