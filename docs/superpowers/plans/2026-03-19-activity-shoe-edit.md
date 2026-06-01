# Activity Shoe Edit Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to assign or change the shoe on an individual activity via an auto-saving dropdown on the ActivityDetail page, constrained to one shoe per activity.

**Architecture:** New `PATCH /api/activities/{id}/shoe` backend endpoint clears existing `ActivityShoe` rows and inserts at most one new row, then triggers static JSON rebuilds. The frontend replaces the read-only shoe display in `ActivityDetail.tsx` with a `<select>` dropdown that fires this endpoint on change.

**Tech Stack:** FastAPI + SQLModel (backend), React 18 + TypeScript + TanStack Query + axios (frontend)

---

## Chunk 1: Backend Endpoint

### Task 1: Add `PATCH /api/activities/{id}/shoe` endpoint

**Files:**
- Modify: `backend/app/routers/activities.py` (after line 313)
- Test: `backend/tests/test_activities.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_activities.py`:

```python
from app.models import Activity, ActivityShoe, Shoe
from datetime import datetime


def _make_activity(session):
    act = Activity(
        source="manual_upload",
        sport_type="running",
        started_at=datetime(2024, 1, 1, 8, 0, 0),
        duration_s=3600,
        distance_m=10000,
        elevation_gain_m=50,
    )
    session.add(act)
    session.commit()
    session.refresh(act)
    return act


def _make_shoe(session, name="Pegasus"):
    shoe = Shoe(name=name, brand="Nike", retired=False)
    session.add(shoe)
    session.commit()
    session.refresh(shoe)
    return shoe


def test_patch_activity_shoe_assigns(client, session):
    from sqlmodel import select as sm_select
    act = _make_activity(session)
    shoe = _make_shoe(session)
    r = client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": shoe.id})
    assert r.status_code == 200
    links = session.exec(sm_select(ActivityShoe).where(ActivityShoe.activity_id == act.id)).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id


def test_patch_activity_shoe_replaces(client, session):
    act = _make_activity(session)
    shoe1 = _make_shoe(session, "Shoe A")
    shoe2 = _make_shoe(session, "Shoe B")
    # Assign first shoe
    client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": shoe1.id})
    # Replace with second shoe
    r = client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": shoe2.id})
    assert r.status_code == 200
    from sqlmodel import select as sm_select
    links = session.exec(sm_select(ActivityShoe).where(ActivityShoe.activity_id == act.id)).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe2.id


def test_patch_activity_shoe_clears(client, session):
    act = _make_activity(session)
    shoe = _make_shoe(session)
    client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": shoe.id})
    r = client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": None})
    assert r.status_code == 200
    from sqlmodel import select as sm_select
    links = session.exec(sm_select(ActivityShoe).where(ActivityShoe.activity_id == act.id)).all()
    assert len(links) == 0


def test_patch_activity_shoe_404(client):
    r = client.patch("/api/activities/999/shoe", json={"shoe_id": 1})
    assert r.status_code == 404


def test_patch_activity_shoe_invalid_shoe(client, session):
    act = _make_activity(session)
    r = client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": 9999})
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python3 -m pytest tests/test_activities.py::test_patch_activity_shoe_assigns tests/test_activities.py::test_patch_activity_shoe_replaces tests/test_activities.py::test_patch_activity_shoe_clears tests/test_activities.py::test_patch_activity_shoe_404 tests/test_activities.py::test_patch_activity_shoe_invalid_shoe -v
```

Expected: all 5 FAIL with 404 or 405 (endpoint doesn't exist yet)

- [ ] **Step 3: Verify `bg_rebuild_globals` is exported from builder**

```bash
cd backend && python3 -c "from app.services.builder import bg_rebuild_globals; print('ok')"
```

Expected: `ok`. If this fails, check `backend/app/services/builder.py` for the correct function name that triggers a full globals rebuild (activities.json + shoes.json).

- [ ] **Step 4: Add the endpoint**

In `backend/app/routers/activities.py`, after line 313 (after the `update_activity` function), add:

```python

@router.patch("/{activity_id}/shoe", status_code=200)
def update_activity_shoe(
    activity_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")

    shoe_id = data.get("shoe_id")
    if shoe_id is not None:
        from app.models import Shoe
        if not session.get(Shoe, shoe_id):
            raise HTTPException(status_code=404, detail="Shoe not found")

    # Clear all existing shoe associations for this activity
    session.exec(sa_delete(ActivityShoe).where(ActivityShoe.activity_id == activity_id))

    # Assign the new shoe if provided
    if shoe_id is not None:
        session.add(ActivityShoe(activity_id=activity_id, shoe_id=shoe_id))

    session.commit()
    _invalidate_list_cache()
    from app.routers.stats import _invalidate_stats_cache
    _invalidate_stats_cache()
    from app.services.builder import bg_rebuild_after_activity_update, bg_rebuild_globals
    background_tasks.add_task(bg_rebuild_after_activity_update, activity_id)
    background_tasks.add_task(bg_rebuild_globals)
    return {"ok": True}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_activities.py::test_patch_activity_shoe_assigns tests/test_activities.py::test_patch_activity_shoe_replaces tests/test_activities.py::test_patch_activity_shoe_clears tests/test_activities.py::test_patch_activity_shoe_404 tests/test_activities.py::test_patch_activity_shoe_invalid_shoe -v
```

Expected: all 5 PASS

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd backend && python3 -m pytest -v
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/activities.py backend/tests/test_activities.py
git commit -m "feat: PATCH /api/activities/{id}/shoe endpoint — assign or clear shoe"
```

---

## Chunk 2: Frontend

### Task 2: Add `updateActivityShoe` to API client

**Files:**
- Modify: `frontend/src/api/client.ts` (after line 81)

- [ ] **Step 1: Add the function**

In `frontend/src/api/client.ts`, after line 81 (`export const updateShoe = ...`), add:

```typescript
export const updateActivityShoe = (activityId: number, shoeId: number | null) =>
  api.patch(`/activities/${activityId}/shoe`, { shoe_id: shoeId }).then((r) => r.data);
```

- [ ] **Step 2: Verify no TypeScript errors**

```bash
cd frontend && npm run build 2>&1 | grep -E "error|Error" | head -20
```

Expected: no errors related to `client.ts`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: add updateActivityShoe API client function"
```

---

### Task 3: Replace read-only shoe display with dropdown in ActivityDetail

**Files:**
- Modify: `frontend/src/pages/ActivityDetail.tsx`

- [ ] **Step 1: Add imports**

In `frontend/src/pages/ActivityDetail.tsx`:

1. Find the existing `@tanstack/react-query` import and ensure `useMutation` and `useQueryClient` are included alongside `useQuery`.

2. Find the existing `../api/client` import and add `updateActivityShoe` and `getShoes` to it (both may already be present — add only what's missing).

3. Find the existing `../types` import (currently `import { Activity, DataPoint, Photo } from "../types"`) and add `Shoe`:
   ```typescript
   import { Activity, DataPoint, Photo, Shoe } from "../types";
   ```

- [ ] **Step 2: Add shoes query and mutation inside the component**

Inside the `ActivityDetail` component function, after the existing `useQuery` calls (around line 343), add:

```typescript
const queryClient = useQueryClient();

const { data: allShoes = [] } = useQuery<Shoe[]>({
  queryKey: ["shoes"],
  queryFn: getShoes,
});

const currentShoeId = shoes && shoes.length > 0 ? shoes[0].id : null;

// Active shoes + currently-assigned shoe (even if retired, so it shows correctly)
const activeShoes = allShoes.filter(
  (s) => !s.retired || s.id === currentShoeId
);

const shoeMutation = useMutation({
  mutationFn: (shoeId: number | null) => updateActivityShoe(actId, shoeId),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["activity-full", actId] });
    queryClient.invalidateQueries({ queryKey: ["shoes"] });
    queryClient.invalidateQueries({ queryKey: ["activities"] });
  },
});
```

Note: `Shoe` type is already imported via `../types`. Check the existing imports — if `Shoe` isn't imported, add it.

- [ ] **Step 3: Replace the read-only shoe display**

Find this block in `ActivityDetail.tsx` (around lines 460–467):

```tsx
{shoes && shoes.length > 0 && (
  <div className="flex items-center gap-2 pt-2 mt-1 text-sm text-gray-600 flex-wrap">
    <span className="text-base leading-none">👟</span>
    {shoes.map((s) => (
      <span key={s.id} className="text-gray-700">{s.name}</span>
    ))}
  </div>
)}
```

Replace it with:

```tsx
<div className="flex items-center gap-2 pt-2 mt-1">
  <span className="text-base leading-none">👟</span>
  <select
    value={currentShoeId ?? ""}
    disabled={shoeMutation.isPending}
    onChange={(e) => {
      const val = e.target.value;
      shoeMutation.mutate(val === "" ? null : parseInt(val, 10));
    }}
    className="text-sm border border-gray-200 rounded px-2 py-0.5 bg-white text-gray-700 disabled:opacity-50"
  >
    <option value="">No shoe</option>
    {activeShoes.map((s) => (
      <option key={s.id} value={s.id}>{s.name}{s.brand ? ` (${s.brand})` : ""}</option>
    ))}
  </select>
  {shoeMutation.isError && (
    <span className="text-xs text-red-500">Failed to save</span>
  )}
</div>
```

- [ ] **Step 4: Build to verify no TypeScript errors**

```bash
cd frontend && npm run build 2>&1 | grep -E "error TS|Error" | head -20
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ActivityDetail.tsx
git commit -m "feat: shoe dropdown on ActivityDetail — auto-saves on change"
```

---

## Chunk 3: Deploy & Verify

### Task 4: Build and push updated images

- [ ] **Step 1: Build images**

```bash
docker compose build
```

- [ ] **Step 2: Push images**

```bash
docker compose push
```

- [ ] **Step 3: Pull and restart on coruscant**

On coruscant:
```bash
cd ~/.docker_config && docker compose pull && docker compose up -d domos_backend domos_frontend
```

- [ ] **Step 4: Manual smoke test**

1. Open an activity detail page
2. Verify the shoe dropdown appears with "No shoe" and all active shoes
3. Select a shoe — verify it saves (no error message, dropdown stays on selection)
4. Reload the page — verify the selected shoe persists
5. Select "No shoe" — verify it clears on reload
