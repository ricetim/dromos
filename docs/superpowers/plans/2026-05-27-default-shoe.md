# Default Shoe + Strava Shoe-Sync Removal — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick a single default shoe on the Gear page. New activities (Coros, Strava-streams, manual upload) are stamped with the default at ingest. Retiring a shoe clears it as default. The pre-existing Strava-gear sync code is excised.

**Architecture:** A nullable `default_shoe_id` column on the existing `UserProfile` singleton stores the choice. A small helper (`stamp_default_shoe`) is called from each of the three ingest sites between `session.flush()` and `session.commit()`. The Gear page UI uses a star-icon column on each active shoe row, wired to `PATCH /api/profile`. The `strava_gear_id` column on `Shoe` and the two shoe-sync sections inside `_sync_strava_activities` are removed; existing `Shoe` and `ActivityShoe` rows are preserved untouched.

**Tech Stack:** Python 3.10, FastAPI, SQLModel (SQLite), pytest, React 18 + TypeScript + Tailwind, React Query, Vite.

**Spec:** [docs/superpowers/specs/2026-05-27-default-shoe-design.md](../specs/2026-05-27-default-shoe-design.md)

---

## File Map

**Create:**
- `backend/app/services/shoe_default.py` — `stamp_default_shoe(session, activity_id)` helper.
- `backend/tests/test_default_shoe.py` — all new tests for this feature.

**Modify:**
- `backend/app/models.py` — add `UserProfile.default_shoe_id`; drop `Shoe.strava_gear_id`.
- `backend/app/database.py` — add migration calls inside `init_db()`.
- `backend/app/routers/profile.py` — allowlist + validation for `default_shoe_id`.
- `backend/app/routers/shoes.py` — retirement-clears-default hook.
- `backend/app/routers/activities.py` — call `stamp_default_shoe` in `/upload`.
- `backend/app/routers/sync.py` — call `stamp_default_shoe` in two ingest paths; excise shoe-sync sections 3 & 4; drop `fetch_athlete` / `fetch_gear` imports; drop `shoes_synced` and `shoe_links_created` from `_last_sync`.
- `backend/app/services/strava.py` — delete `fetch_athlete` and `fetch_gear` (now unused).
- `backend/app/services/builder.py` — emit `is_default: bool` per shoe in `shoes.json`.
- `frontend/src/api/client.ts` — add `setDefaultShoe(id)` helper.
- `frontend/src/pages/Gear.tsx` — extend `Shoe` interface; add star-button column + `setDefaultMutation`.

---

## Chunk 1: Backend — schema, helper, ingest, API

### Task 1: Add `default_shoe_id` column to UserProfile

**Files:**
- Modify: `backend/app/models.py:92-103` (UserProfile class)
- Modify: `backend/app/database.py:38-45` (add `_add_column` call alongside weather columns)
- Test: `backend/tests/test_default_shoe.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_default_shoe.py`:

```python
from sqlmodel import Session, select
from app.models import UserProfile, Shoe


def test_userprofile_has_default_shoe_id_field(session: Session):
    """UserProfile should have a nullable default_shoe_id column."""
    profile = UserProfile(id=1, default_shoe_id=None)
    session.add(profile)
    session.commit()
    refreshed = session.get(UserProfile, 1)
    assert refreshed is not None
    assert refreshed.default_shoe_id is None


def test_userprofile_can_set_default_shoe_id(session: Session):
    shoe = Shoe(name="Test Shoe")
    session.add(shoe)
    session.commit()
    session.refresh(shoe)

    profile = UserProfile(id=1, default_shoe_id=shoe.id)
    session.add(profile)
    session.commit()
    refreshed = session.get(UserProfile, 1)
    assert refreshed.default_shoe_id == shoe.id
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: FAIL with `TypeError: 'default_shoe_id' is an invalid keyword argument for UserProfile`.

- [ ] **Step 3: Add the field to UserProfile**

Edit `backend/app/models.py`. Find the `UserProfile` class (line 92) and add `default_shoe_id` to it:

```python
class UserProfile(SQLModel, table=True):
    """Singleton row (id=1) storing user-specific physiology settings."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # ... existing fields ...
    default_shoe_id: Optional[int] = Field(default=None, foreign_key="shoe.id")
```

(Insert `default_shoe_id` as the **last** field in the class — keeps the migration column order stable.)

- [ ] **Step 4: Add migration to `init_db()`**

Edit `backend/app/database.py`. After the existing `_add_column` calls (around line 45, after `_add_column(conn, "activity", "weather_is_daytime", "INTEGER")`), add:

```python
        _add_column(conn, "userprofile", "default_shoe_id", "INTEGER")
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: both tests PASS.

- [ ] **Step 6: Run the full backend test suite to confirm no regressions**

```bash
cd backend && python3 -m pytest -v
```

Expected: all tests pass (58 existing + 2 new = 60).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/database.py backend/tests/test_default_shoe.py
git commit -m "feat(models): add default_shoe_id to UserProfile"
```

---

### Task 2: Drop `strava_gear_id` column from Shoe

**Files:**
- Modify: `backend/app/models.py:78` (remove `strava_gear_id`)
- Modify: `backend/app/database.py` (add guarded `DROP COLUMN`)

- [ ] **Step 1: Remove `strava_gear_id` from the Shoe model**

Edit `backend/app/models.py:78` — delete the line:

```python
    strava_gear_id: Optional[str] = None   # e.g. "g12345678" — used as dedup key on sync
```

- [ ] **Step 2: Add the column-drop migration**

Edit `backend/app/database.py`. Inside the `with engine.begin() as conn:` block, after the new `_add_column` line for `default_shoe_id`, add:

```python
        # Drop vestigial Strava gear id; SQLite 3.35+ supports DROP COLUMN.
        # Wrapped in try/except for idempotency on already-migrated DBs.
        try:
            conn.exec_driver_sql("ALTER TABLE shoe DROP COLUMN strava_gear_id")
        except Exception:
            pass
```

- [ ] **Step 3: Run the suite to confirm nothing references the dropped field**

```bash
cd backend && python3 -m pytest -v
```

Expected: all 60 tests pass. (If anything fails referencing `strava_gear_id`, that's a leftover from Task 9's prep work — fix in this task by also touching that reference.)

- [ ] **Step 4: grep for any stragglers**

```bash
grep -rn "strava_gear_id" backend/app/ backend/tests/
```

Expected output: no matches.

If matches appear: open each file and remove the reference (likely in `sync.py` — anticipated for Task 9, but if it shows up here, handle it now). Re-run the test suite.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/database.py
git commit -m "refactor(models): drop vestigial Shoe.strava_gear_id column"
```

---

### Task 3: Create `stamp_default_shoe` helper

**Files:**
- Create: `backend/app/services/shoe_default.py`
- Test: `backend/tests/test_default_shoe.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_default_shoe.py`:

```python
from app.models import ActivityShoe, Activity
from app.services.shoe_default import stamp_default_shoe
from datetime import datetime


def _make_activity(session: Session) -> Activity:
    act = Activity(
        source="test",
        started_at=datetime(2026, 5, 27, 8, 0, 0),
        distance_m=5000,
        duration_s=1500,
        elevation_gain_m=10,
        sport_type="run",
    )
    session.add(act)
    session.flush()
    return act


def test_stamp_default_shoe_no_default_no_link(session: Session):
    """When no default is set, stamp is a no-op."""
    session.add(UserProfile(id=1, default_shoe_id=None))
    act = _make_activity(session)
    stamp_default_shoe(session, act.id)
    session.commit()

    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == act.id)
    ).all()
    assert links == []


def test_stamp_default_shoe_writes_link(session: Session):
    """When a default is set, a single ActivityShoe link is written."""
    shoe = Shoe(name="Test Shoe")
    session.add(shoe)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=shoe.id))
    act = _make_activity(session)

    stamp_default_shoe(session, act.id)
    session.commit()

    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == act.id)
    ).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py::test_stamp_default_shoe_writes_link -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.shoe_default'`.

- [ ] **Step 3: Create the helper**

Create `backend/app/services/shoe_default.py`:

```python
from sqlmodel import Session
from app.models import ActivityShoe, UserProfile


def stamp_default_shoe(session: Session, activity_id: int) -> None:
    """If the user has a default shoe configured, write a single ActivityShoe
    link for the given activity. Caller must `session.commit()` afterwards.

    No-op when no default is set or no UserProfile row exists. Relies on the
    unique index `idx_activityshoe_activity_id_unique` to prevent duplicates
    if accidentally called twice for the same activity.
    """
    profile = session.get(UserProfile, 1)
    if profile and profile.default_shoe_id:
        session.add(ActivityShoe(
            activity_id=activity_id,
            shoe_id=profile.default_shoe_id,
        ))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: all 4 tests in this file PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/shoe_default.py backend/tests/test_default_shoe.py
git commit -m "feat(services): add stamp_default_shoe helper"
```

---

### Task 4: Profile API — allow + validate `default_shoe_id`

**Files:**
- Modify: `backend/app/routers/profile.py` (extend allowlist + validation)
- Test: `backend/tests/test_default_shoe.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_default_shoe.py`:

```python
def test_patch_profile_sets_default_shoe(client, session):
    """PATCH /api/profile {default_shoe_id: N} updates the profile."""
    shoe = Shoe(name="Tracer")
    session.add(shoe)
    session.add(UserProfile(id=1))
    session.commit()
    session.refresh(shoe)

    r = client.patch("/api/profile", json={"default_shoe_id": shoe.id})
    assert r.status_code == 200
    assert r.json()["default_shoe_id"] == shoe.id


def test_patch_profile_clears_default_shoe(client, session):
    """PATCH /api/profile {default_shoe_id: null} clears the default."""
    shoe = Shoe(name="Tracer")
    session.add(shoe)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=shoe.id))
    session.commit()

    r = client.patch("/api/profile", json={"default_shoe_id": None})
    assert r.status_code == 200
    assert r.json()["default_shoe_id"] is None


def test_patch_profile_rejects_missing_shoe(client, session):
    session.add(UserProfile(id=1))
    session.commit()
    r = client.patch("/api/profile", json={"default_shoe_id": 9999})
    assert r.status_code == 400


def test_patch_profile_rejects_retired_shoe(client, session):
    shoe = Shoe(name="Old", retired=True)
    session.add(shoe)
    session.add(UserProfile(id=1))
    session.commit()
    session.refresh(shoe)
    r = client.patch("/api/profile", json={"default_shoe_id": shoe.id})
    assert r.status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v -k "patch_profile"
```

Expected: at least one test FAILS (the allowlist in `profile.py:23` currently strips unknown keys, so `default_shoe_id` is silently dropped).

- [ ] **Step 3: Extend the allowlist + add validation**

Edit `backend/app/routers/profile.py`. Replace the `update_profile` body with:

```python
@router.patch("")
def update_profile(data: dict, session: Session = Depends(get_session)):
    profile = session.get(UserProfile, 1)
    if not profile:
        profile = UserProfile(id=1)
        session.add(profile)

    ALLOWED = {
        # ... keep existing keys exactly as they are; do NOT remove any ...
        "default_shoe_id",
    }
    # IMPORTANT: preserve existing allowlist keys above — only ADD default_shoe_id.

    if "default_shoe_id" in data:
        new_id = data["default_shoe_id"]
        if new_id is not None:
            from app.models import Shoe
            shoe = session.get(Shoe, new_id)
            if not shoe:
                raise HTTPException(status_code=400, detail="Shoe not found")
            if shoe.retired:
                raise HTTPException(status_code=400, detail="Cannot set retired shoe as default")

    for key in data:
        if key in ALLOWED:
            setattr(profile, key, data[key])
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile
```

**Important:** open the current `profile.py` first to see the existing allowlist (it may currently be implicit via `for key in data` without filtering). If no allowlist exists, introduce one as shown — and include every existing field name that was previously accepted. Otherwise this task silently breaks profile updates.

Also add the import at the top:

```python
from fastapi import APIRouter, Depends, HTTPException
```

(Add `HTTPException` to the existing FastAPI import line.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: all 8 tests in this file PASS.

- [ ] **Step 5: Run the full suite**

```bash
cd backend && python3 -m pytest -v
```

Expected: all tests pass (no regression in profile-related tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/profile.py backend/tests/test_default_shoe.py
git commit -m "feat(profile): accept and validate default_shoe_id"
```

---

### Task 5: Retiring the default shoe clears it from the profile

**Files:**
- Modify: `backend/app/routers/shoes.py:36-47` (update_shoe)
- Test: `backend/tests/test_default_shoe.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_default_shoe.py`:

```python
def test_retiring_default_shoe_clears_profile(client, session):
    """PATCH /api/shoes/{id} retired=True clears UserProfile.default_shoe_id."""
    shoe = Shoe(name="Speed")
    session.add(shoe)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=shoe.id))
    session.commit()
    session.refresh(shoe)

    r = client.patch(f"/api/shoes/{shoe.id}", json={"retired": True})
    assert r.status_code == 200

    profile = session.get(UserProfile, 1)
    session.refresh(profile)
    assert profile.default_shoe_id is None


def test_retiring_non_default_shoe_does_not_touch_profile(client, session):
    a = Shoe(name="A")
    b = Shoe(name="B")
    session.add(a)
    session.add(b)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=a.id))
    session.commit()
    session.refresh(a)
    session.refresh(b)

    r = client.patch(f"/api/shoes/{b.id}", json={"retired": True})
    assert r.status_code == 200

    profile = session.get(UserProfile, 1)
    session.refresh(profile)
    assert profile.default_shoe_id == a.id
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v -k "retir"
```

Expected: `test_retiring_default_shoe_clears_profile` FAILS (default not cleared).

- [ ] **Step 3: Add the clear-default logic to `update_shoe`**

Edit `backend/app/routers/shoes.py`. In `update_shoe`, after the `setattr` loop and before `session.add(shoe)`:

```python
    # If this shoe just became retired and is the current default, clear the default.
    if shoe.retired:
        from app.models import UserProfile
        profile = session.get(UserProfile, 1)
        if profile and profile.default_shoe_id == shoe.id:
            profile.default_shoe_id = None
            session.add(profile)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: all tests pass (now 10 in this file).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/shoes.py backend/tests/test_default_shoe.py
git commit -m "feat(shoes): clear default on retirement"
```

---

### Task 6: Stamp default shoe in manual `/upload`

**Files:**
- Modify: `backend/app/routers/activities.py:198-268` (upload_fit)
- Test: `backend/tests/test_default_shoe.py` (append)

- [ ] **Step 1: Write the failing test**

This test needs a real `.fit` file. The fixture path is `backend/tests/fixtures/sample.fit` (per `debug.md`). Append:

```python
import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SAMPLE_FIT = FIXTURES / "sample.fit"


def _seed_default_shoe(session) -> Shoe:
    shoe = Shoe(name="DefaultTest")
    session.add(shoe)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=shoe.id))
    session.commit()
    session.refresh(shoe)
    return shoe


@pytest.mark.skipif(not SAMPLE_FIT.exists(), reason="sample.fit fixture required")
def test_upload_stamps_default_shoe(client, session):
    import pytest  # noqa: re-import inside guarded scope
    shoe = _seed_default_shoe(session)

    with SAMPLE_FIT.open("rb") as f:
        r = client.post(
            "/api/activities/upload",
            files={"file": ("sample.fit", f, "application/octet-stream")},
        )
    assert r.status_code == 201
    act_id = r.json()["id"]

    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == act_id)
    ).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id


@pytest.mark.skipif(not SAMPLE_FIT.exists(), reason="sample.fit fixture required")
def test_upload_without_default_creates_no_link(client, session):
    session.add(UserProfile(id=1, default_shoe_id=None))
    session.commit()

    with SAMPLE_FIT.open("rb") as f:
        r = client.post(
            "/api/activities/upload",
            files={"file": ("sample.fit", f, "application/octet-stream")},
        )
    assert r.status_code == 201
    act_id = r.json()["id"]

    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == act_id)
    ).all()
    assert links == []
```

Also add the top-of-file import for `pytest`:

```python
import pytest
```

(if not already present from earlier tests in this file).

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v -k "upload"
```

Expected: FAIL (or SKIP if no sample.fit; if SKIP, you cannot validate this task — verify manually in Task 13 instead).

- [ ] **Step 3: Wire `stamp_default_shoe` into the upload route**

Edit `backend/app/routers/activities.py`. At the top, add the import (after the existing `from app.services...` lines):

```python
from app.services.shoe_default import stamp_default_shoe
```

In `upload_fit`, between `session.flush()` (line 230) and the `for dp in result.datapoints:` loop, add:

```python
    stamp_default_shoe(session, act.id)
```

The single `session.commit()` at line 247 will cover the stamped row.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: all tests pass (skipped if no sample.fit).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/activities.py backend/tests/test_default_shoe.py
git commit -m "feat(upload): stamp default shoe on manual FIT upload"
```

---

### Task 7: Stamp default shoe in Coros sync

**Files:**
- Modify: `backend/app/routers/sync.py:282-354` (_sync_coros)
- Test: `backend/tests/test_default_shoe.py` (append)

- [ ] **Step 1: Write the failing test**

This test mocks the Coros service. Append to `backend/tests/test_default_shoe.py`:

```python
from unittest.mock import patch as mock_patch


def test_sync_coros_stamps_default_shoe(session, tmp_path):
    """When _sync_coros ingests a new activity, the default shoe is stamped."""
    from app.routers import sync as sync_mod
    from app.services.fit_parser import ParseResult

    shoe = _seed_default_shoe(session)

    fake_meta = [{
        "labelId": "test-ext-1",
        "sportType": "100",
        "name": "Test Run",
    }]
    fake_parse = ParseResult(
        started_at=datetime(2026, 5, 27, 7, 0, 0),
        distance_m=5000,
        duration_s=1500,
        elevation_gain_m=10,
        elevation_loss_m=10,
        avg_hr=140,
        sport_type="run",
        datapoints=[],
        laps=[],
    )
    fake_detail = {"notes": None, "rpe": None}

    # Patch the helpers to avoid network and FIT-parsing
    with mock_patch.object(sync_mod, "coros_login", return_value=("tok", "uid")), \
         mock_patch.object(sync_mod, "coros_list", return_value=fake_meta), \
         mock_patch.object(sync_mod, "download_fit", return_value=b"\x00\x00"), \
         mock_patch.object(sync_mod, "get_activity_detail", return_value=fake_detail), \
         mock_patch.object(sync_mod, "parse_fit_file", return_value=fake_parse), \
         mock_patch.object(sync_mod, "fetch_weather", return_value=None), \
         mock_patch.object(sync_mod, "bg_rebuild_all", return_value=None), \
         mock_patch.object(sync_mod, "engine", session.bind), \
         mock_patch.object(sync_mod, "DATA_DIR", tmp_path), \
         mock_patch.object(sync_mod, "COROS_EMAIL", "test@example.com"), \
         mock_patch.object(sync_mod, "COROS_PASSWORD", "pw"):
        sync_mod._sync_coros()

    # Re-query in this session
    acts = session.exec(select(Activity)).all()
    assert len(acts) == 1
    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == acts[0].id)
    ).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id
```

(If `ParseResult` differs from this shape, open `backend/app/services/fit_parser.py` and adjust the construction to match.)

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v -k "coros"
```

Expected: FAIL (no `ActivityShoe` row created).

- [ ] **Step 3: Wire `stamp_default_shoe` into `_sync_coros`**

Edit `backend/app/routers/sync.py`. Add the import at the top, alongside other `app.services` imports:

```python
from app.services.shoe_default import stamp_default_shoe
```

In `_sync_coros`, immediately after `session.flush()` (line 322), add:

```python
                stamp_default_shoe(session, act.id)
```

The surrounding `session.commit()` at line 348 covers this.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/sync.py backend/tests/test_default_shoe.py
git commit -m "feat(sync): stamp default shoe on Coros ingest"
```

---

### Task 8: Stamp default shoe in Strava-streams ingest

**Files:**
- Modify: `backend/app/routers/sync.py:114-196` (unmatched Strava import loop)
- Test: `backend/tests/test_default_shoe.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_default_shoe.py`:

```python
def test_strava_streams_import_stamps_default_shoe(session, tmp_path):
    """When _sync_strava_activities imports an unmatched Strava activity, default is stamped."""
    from app.routers import sync as sync_mod

    shoe = _seed_default_shoe(session)

    fake_strava_act = {
        "id": 12345,
        "start_date": "2026-05-27T07:00:00Z",
        "sport_type": "Run",
        "distance": 5000,
        "moving_time": 1500,
        "total_elevation_gain": 10,
        "name": "Test Strava Run",
    }

    with mock_patch.object(sync_mod, "get_access_token", return_value="tok"), \
         mock_patch.object(sync_mod, "fetch_athlete_activities", return_value=[fake_strava_act]), \
         mock_patch.object(sync_mod, "fetch_activity_streams", return_value={}), \
         mock_patch.object(sync_mod, "streams_to_datapoints", return_value=[]), \
         mock_patch.object(sync_mod, "fetch_activity_laps", return_value=[]), \
         mock_patch.object(sync_mod, "sync_photos_for_activity", return_value=0), \
         mock_patch.object(sync_mod, "fetch_weather", return_value=None), \
         mock_patch.object(sync_mod, "bg_rebuild_all", return_value=None), \
         mock_patch.object(sync_mod, "engine", session.bind), \
         mock_patch.object(sync_mod, "STRAVA_REFRESH_TOKEN", "rtok"):
        sync_mod._sync_strava_activities()

    acts = session.exec(select(Activity).where(Activity.strava_id == "12345")).all()
    assert len(acts) == 1
    links = session.exec(
        select(ActivityShoe).where(ActivityShoe.activity_id == acts[0].id)
    ).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v -k "strava_streams"
```

Expected: FAIL.

- [ ] **Step 3: Wire `stamp_default_shoe` into the unmatched-import loop**

Edit `backend/app/routers/sync.py`. Inside the `for sa in unmatched:` loop (starts at line 115), after `session.flush()` (line 150) and before the `for dp in dps:` loop (line 152), add:

```python
                stamp_default_shoe(session, act.id)
```

(The import was already added in Task 7.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/sync.py backend/tests/test_default_shoe.py
git commit -m "feat(sync): stamp default shoe on Strava-streams ingest"
```

---

### Task 9: Remove Strava shoe-sync logic

**Files:**
- Modify: `backend/app/routers/sync.py` — delete sections 3 & 4, drop imports, drop `_last_sync` keys
- Test: `backend/tests/test_default_shoe.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_default_shoe.py`:

```python
def test_strava_sync_does_not_touch_existing_shoes(session, tmp_path):
    """After removal of shoe sync, _sync_strava_activities leaves Shoe/ActivityShoe untouched."""
    from app.routers import sync as sync_mod

    # Seed an existing shoe + link manually
    shoe = Shoe(name="Pre-existing")
    session.add(shoe)
    session.flush()
    act = Activity(
        source="manual_upload",
        started_at=datetime(2026, 5, 26, 7, 0, 0),
        distance_m=5000, duration_s=1500, elevation_gain_m=10,
        sport_type="run",
    )
    session.add(act)
    session.flush()
    session.add(ActivityShoe(activity_id=act.id, shoe_id=shoe.id))
    session.commit()
    initial_shoe_count = len(session.exec(select(Shoe)).all())
    initial_link_count = len(session.exec(select(ActivityShoe)).all())

    # Strava sync returns an "athlete" with shoes — but the code should ignore it.
    with mock_patch.object(sync_mod, "get_access_token", return_value="tok"), \
         mock_patch.object(sync_mod, "fetch_athlete_activities", return_value=[]), \
         mock_patch.object(sync_mod, "sync_photos_for_activity", return_value=0), \
         mock_patch.object(sync_mod, "bg_rebuild_all", return_value=None), \
         mock_patch.object(sync_mod, "engine", session.bind), \
         mock_patch.object(sync_mod, "STRAVA_REFRESH_TOKEN", "rtok"):
        sync_mod._sync_strava_activities()

    assert len(session.exec(select(Shoe)).all()) == initial_shoe_count
    assert len(session.exec(select(ActivityShoe)).all()) == initial_link_count
    # Also verify the keys are gone from the status payload
    assert "shoes_synced" not in sync_mod._last_sync
    assert "shoe_links_created" not in sync_mod._last_sync
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v -k "does_not_touch"
```

Expected: FAIL (the status payload still contains the keys; mock_patch for `fetch_athlete` is also missing so the test errors).

- [ ] **Step 3: Excise sections 3 & 4 from `_sync_strava_activities`**

Edit `backend/app/routers/sync.py`. Delete the entire block from line 198 through line 254 — everything from the comment `# ── 3. Upsert shoes from athlete profile ...` through the `session.commit()` at the end of section 4. (The line right above, `session.commit()` at the end of section 2b, should remain; the next code after the deletion is `# ── 5. Photo sync ...`.)

Also delete the `gear_map: dict[str, list[int]] = {}` initialization (line 75), and the two `gear_map.setdefault(...)` blocks at lines 95-97 and 180-183 — they're now dead.

- [ ] **Step 4: Drop the now-unused imports**

Edit the import line at `sync.py:5-8`:

```python
from app.services.strava import (
    get_access_token, fetch_athlete_activities, sync_photos_for_activity,
    fetch_activity_streams, streams_to_datapoints, fetch_activity_laps,
)
```

(Remove `fetch_athlete` and `fetch_gear`.)

- [ ] **Step 5: Drop the now-unused keys from the `_last_sync` payload**

In the success-branch of `_sync_strava_activities`, the `_last_sync = { ... }` dict (around line 264) currently has keys `"shoes_synced"` and `"shoe_links_created"`. Remove those two keys:

```python
            _last_sync = {
                "status": "ok",
                "ts": datetime.now(timezone.utc).isoformat(),
                "matched_activities": matched_count,
                "strava_activities_imported": streams_imported,
                "new_photos": new_photos,
                "error": None,
            }
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Run the full suite**

```bash
cd backend && python3 -m pytest -v
```

Expected: all tests pass. If any test in `test_strava.py` references `fetch_athlete` / `fetch_gear` or expects `shoes_synced` / `shoe_links_created` in the status, update it as part of this task — keeping unrelated tests green.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/sync.py backend/tests/test_default_shoe.py
git commit -m "refactor(sync): remove Strava shoe-sync logic"
```

---

### Task 10: Delete unused `fetch_athlete` and `fetch_gear` from Strava service

**Files:**
- Modify: `backend/app/services/strava.py`

- [ ] **Step 1: Confirm zero references**

```bash
grep -rn "fetch_athlete\b\|fetch_gear" backend/app/ backend/tests/
```

Expected output: no matches outside `backend/app/services/strava.py` (the definitions themselves). If `test_strava.py` has tests for these functions, decide:
- If the tests are non-trivial and the functions might be reused later → keep both, end the task here.
- Otherwise → also delete the tests.

- [ ] **Step 2: Delete the function definitions**

Edit `backend/app/services/strava.py`. Delete the `def fetch_athlete(...)` function (around line 27) and the `def fetch_gear(...)` function (around line 57).

- [ ] **Step 3: Run the suite**

```bash
cd backend && python3 -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/strava.py backend/tests/
git commit -m "chore(strava): remove unused fetch_athlete and fetch_gear"
```

---

### Task 11: Builder emits `is_default` on each shoe in `shoes.json`

**Files:**
- Modify: `backend/app/services/builder.py:473-506` (_rebuild_shoes)
- Test: `backend/tests/test_default_shoe.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_default_shoe.py`:

```python
import json


def test_rebuild_shoes_emits_is_default(session, tmp_path):
    from app.services.builder import _rebuild_shoes
    from app.models import UserProfile

    a = Shoe(name="A")
    b = Shoe(name="B")
    session.add(a)
    session.add(b)
    session.flush()
    session.add(UserProfile(id=1, default_shoe_id=a.id))
    session.commit()

    _rebuild_shoes(session, tmp_path)

    data = json.loads((tmp_path / "shoes.json").read_text())
    by_name = {s["name"]: s for s in data}
    assert by_name["A"]["is_default"] is True
    assert by_name["B"]["is_default"] is False


def test_rebuild_shoes_no_default(session, tmp_path):
    from app.services.builder import _rebuild_shoes

    a = Shoe(name="A")
    session.add(a)
    session.add(UserProfile(id=1, default_shoe_id=None))
    session.commit()

    _rebuild_shoes(session, tmp_path)

    data = json.loads((tmp_path / "shoes.json").read_text())
    assert all(s["is_default"] is False for s in data)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v -k "rebuild_shoes"
```

Expected: FAIL — `is_default` key missing.

- [ ] **Step 3: Update `_rebuild_shoes`**

Edit `backend/app/services/builder.py`. In `_rebuild_shoes` (line 473), after the existing query setup and before the result-building list comprehension (around line 498), read the current default:

```python
    from app.models import UserProfile
    profile = session.get(UserProfile, 1)
    default_id = profile.default_shoe_id if profile else None
```

Then in the per-shoe dict construction (around line 499-505), add `is_default`:

```python
    result = [
        {
            **shoe.model_dump(),
            "total_distance_km": round(cum_m.get(shoe.id, 0.0) / 1000, 1),
            "activity_ids": sorted(act_ids.get(shoe.id, []), reverse=True),
            "timeline": timelines.get(shoe.id, []),
            "years": sorted(years.get(shoe.id, [])),
            "is_default": shoe.id == default_id,
        }
        for shoe in shoes
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_default_shoe.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run the full backend suite**

```bash
cd backend && python3 -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/builder.py backend/tests/test_default_shoe.py
git commit -m "feat(builder): emit is_default per shoe in shoes.json"
```

---

## Chunk 2: Frontend + verification

### Task 12: Frontend — star-icon column on the Gear page

**Files:**
- Modify: `frontend/src/api/client.ts` — add `setDefaultShoe` helper.
- Modify: `frontend/src/pages/Gear.tsx` — extend `Shoe` interface; add star button + mutation.

- [ ] **Step 1: Add the API helper**

Edit `frontend/src/api/client.ts`. Below the existing `updateActivityShoe` (line ~83), add:

```ts
export const setDefaultShoe = (shoeId: number | null) =>
  api.patch("/profile", { default_shoe_id: shoeId }).then((r) => r.data);
```

- [ ] **Step 2: Extend the local `Shoe` interface**

Edit `frontend/src/pages/Gear.tsx`. Find the `interface Shoe { ... }` block (line 17). Add:

```ts
  is_default: boolean;
```

(Insert near the top of the interface, alongside `retired`.)

- [ ] **Step 3: Import the helper**

At the top of `Gear.tsx` (line 7), extend the import:

```ts
import { getShoes, createShoe, updateShoe, setDefaultShoe } from "../api/client";
```

- [ ] **Step 4: Add the mutation**

Inside `export default function Gear()`, after the existing `retireMutation` (line ~212), add:

```ts
  const defaultMutation = useMutation({
    mutationFn: (shoeId: number | null) => setDefaultShoe(shoeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shoes"] }),
  });
```

- [ ] **Step 5: Add the star button as the leftmost element of each active shoe row**

In the active-shoes block (`Gear.tsx:309-331`), wrap the existing row contents. The current structure is:

```tsx
<div key={shoe.id} className="flex items-center p-4 hover:bg-gray-50 ...">
  <Link to={...} className="flex-1 min-w-0"> ... </Link>
  <div className="text-right ml-4 flex-shrink-0"> ... </div>
</div>
```

Add a button before the `<Link>`:

```tsx
<div key={shoe.id} className="flex items-center p-4 hover:bg-gray-50 transition-colors">
  <button
    onClick={() =>
      defaultMutation.mutate(shoe.is_default ? null : shoe.id)
    }
    aria-label={shoe.is_default ? "Default shoe" : "Set as default"}
    className={`mr-3 text-xl leading-none transition-colors ${
      shoe.is_default ? "text-yellow-500" : "text-gray-300 hover:text-yellow-400"
    }`}
    disabled={defaultMutation.isPending}
  >
    {shoe.is_default ? "★" : "☆"}
  </button>
  <Link to={`/activities?shoe=${shoe.id}`} className="flex-1 min-w-0">
    ...
  </Link>
  <div className="text-right ml-4 flex-shrink-0">
    ...
  </div>
</div>
```

**Important:** retired shoes (`Gear.tsx:344-359`) do **not** get the star button. Leave that block unchanged.

- [ ] **Step 6: Type-check the frontend**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 7: Manual browser test**

If the dev server isn't already running, start it (`cd frontend && npm run dev` and `cd backend && uvicorn app.main:app --reload`). Open http://localhost:5173/gear.

Verify:
- Each active shoe has an outlined gray star to its left.
- Click the star on any shoe → it fills gold; the other shoes' stars stay outlined.
- Refresh the page → the chosen shoe's star is still filled.
- Click the filled star → it returns to outlined; no shoe has a filled star.
- Retire a shoe that is currently the default → its row moves to the Retired section (no star). The default is now cleared (no shoe has a filled star).
- The Retired section never shows star buttons.
- Try selecting a retired shoe via direct API call: `curl -X PATCH http://localhost:8000/api/profile -H 'Content-Type: application/json' -d '{"default_shoe_id": <retired_shoe_id>}'` → returns HTTP 400.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/pages/Gear.tsx
git commit -m "feat(gear): star-icon column for selecting default shoe"
```

---

### Task 13: End-to-end smoke + closeout

This task has no code changes — it verifies the integrated behavior, then closes out memory / docs.

- [ ] **Step 1: Trigger a Strava sync**

In the browser (Settings/Sync trigger button) or via:
```bash
curl -X POST http://localhost:8000/api/sync/trigger
```

Wait a few seconds, then:
```bash
curl http://localhost:8000/api/sync/status
```

Expected: `status: ok`. Payload contains `matched_activities`, `strava_activities_imported`, `new_photos`. **No `shoes_synced` or `shoe_links_created` keys** (proves the excision worked).

- [ ] **Step 2: Verify Strava-imported shoes are intact**

Open the Gear page. Any shoes that were created by past Strava syncs should still be present with their accumulated mileage. (Spec calls this out as a non-destructive requirement.)

- [ ] **Step 3: Set a default shoe**

Click the star on one active shoe.

- [ ] **Step 4: Upload a `.fit` file**

From the Activities page, upload one of the files in `data-dev/fit_files/` (or any `.fit` you have handy). After upload completes, open the new activity. The "Shoe" field should show the default shoe you just selected.

- [ ] **Step 5: Retire the default shoe**

On the Gear page, click "Retire" on the currently-default shoe. Verify:
- The shoe moves to the Retired section.
- No shoe in the active section has a filled star.

- [ ] **Step 6: Upload another `.fit`**

Upload a second `.fit`. Verify the new activity has **no** shoe assigned.

- [ ] **Step 7: Update MEMORY.md**

Edit `/home/tim/.claude/projects/-home-tim-projects-dromos/memory/MEMORY.md`. Update the line under "Known Code Patterns":
- Replace `Strava integration: only photos currently; gear/shoe sync not yet implemented (plan in requirements.md)` with:
  `Strava integration: photos only. Shoe assignment is in-app via a "default shoe" on the Gear page (UserProfile.default_shoe_id); stamped at ingest in Coros/Strava-stream/manual-upload paths.`

- [ ] **Step 8: Update requirements.md**

Edit `requirements.md`. In the 2026-03-06 feature backlog, change item #1 from "Strava shoe auto-import (see above)" to `~~Strava shoe auto-import~~ (removed; replaced by in-app default shoe — see specs/2026-05-27-default-shoe-design.md)`.

- [ ] **Step 9: Final commit**

```bash
git add requirements.md /home/tim/.claude/projects/-home-tim-projects-dromos/memory/MEMORY.md
git commit -m "docs: record default-shoe replacement of Strava gear sync"
```

(If MEMORY.md lives outside the repo, commit only `requirements.md`.)

---

## Risk register (for the code reviewer)

- **Stamp ordering inside loops.** Task 8 places the stamp inside the Strava-streams `for sa in unmatched:` loop. The unique index on `activityshoe.activity_id` makes a duplicate-stamp scenario fail loudly — that's desired. Confirm during review that `stamp_default_shoe` is called exactly once per new activity in that loop, after `session.flush()` and before any later `session.flush()` for the same activity.
- **Allowlist in `profile.py`.** Task 4 introduces an allowlist if one doesn't exist. If the current code accepts arbitrary keys (no allowlist), make sure every previously-accepted field is in the new `ALLOWED` set — otherwise this task silently breaks unrelated profile-edit flows. Open `profile.py` before editing and enumerate every field name that legitimate clients send.
- **`strava_gear_id` drop is one-way.** SQLite's `ALTER TABLE DROP COLUMN` is non-reversible without a table rebuild. The try/except in the migration makes the operation idempotent, but a rollback PR cannot restore the column trivially. If unsure, run the full suite plus a manual sync against the dev DB before merging.
- **`PATCH /api/profile` validation runs BEFORE the `for key in data` loop sets the value.** That ordering matters: we lookup the shoe first, then set the attribute. Review the diff to confirm.
- **Mocked tests are coupled to internal module structure.** Tasks 7-9 use `mock_patch.object(sync_mod, ...)` for many helpers. If `_sync_coros` or `_sync_strava_activities` are refactored later, these tests will need updating in lockstep. Acceptable for a personal-app codebase but worth flagging.
