# Activity Keyboard Navigation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to press ArrowRight/ArrowLeft on an activity detail page to navigate to the chronologically older/newer activity.

**Architecture:** A `useEffect` in `ActivityDetail.tsx` registers a `keydown` listener on `window`. It finds the current activity's index in the cached activities list (newest-first) and calls `useNavigate` to move ±1. Input elements are excluded to prevent conflicts with the notes field and shoe dropdown.

**Tech Stack:** React 18, React Router v6, TanStack Query v5, TypeScript

---

## Chunk 1: Keyboard Navigation

### Task 1: Add arrow-key navigation to ActivityDetail

**Files:**
- Modify: `frontend/src/pages/ActivityDetail.tsx`

**Context for implementer:**

- The activities list is already served as `/static/activities.json` and fetched via `getActivities()` in `frontend/src/api/client.ts`. It returns activities sorted newest-first (by `started_at DESC`).
- `ActivityDetail.tsx` currently imports from `react-router-dom` on line 2 — `useNavigate` is not yet imported but is available from the same package.
- `getActivities` is not yet imported in this file — it needs to be added to the existing `../api/client` import on line 4.
- The `Activity` type is already imported on line 5.
- `actId` (the current activity's numeric ID) is already available at line 299.
- There are no frontend unit tests in this project — verification is via TypeScript build + manual check.

---

- [ ] **Step 1: Add `useNavigate` to the react-router-dom import**

In `frontend/src/pages/ActivityDetail.tsx`, line 2, change:

```typescript
import { useParams, Link, useSearchParams } from "react-router-dom";
```

to:

```typescript
import { useParams, Link, useSearchParams, useNavigate } from "react-router-dom";
```

- [ ] **Step 2: Add `getActivities` to the api/client import**

On line 4, change:

```typescript
import { getActivityFull, getDataPoints, getPhotos, getPersonalBests, getVdot, updateActivityShoe, getShoes } from "../api/client";
```

to:

```typescript
import { getActivityFull, getDataPoints, getPhotos, getPersonalBests, getVdot, updateActivityShoe, getShoes, getActivities } from "../api/client";
```

- [ ] **Step 3: Add `useNavigate` and activities query inside the component**

Inside the `ActivityDetail` function, directly after line 299 (`const actId = Number(id);`), add:

```typescript
const navigate = useNavigate();

const { data: activities = [] } = useQuery<Activity[]>({
  queryKey: ["activities"],
  queryFn: getActivities,
});
```

- [ ] **Step 4: Add the `useEffect` keydown listener**

Directly after the `useNavigate` and activities query (after the block added in step 3), add:

```typescript
useEffect(() => {
  const handleKeyDown = (e: KeyboardEvent) => {
    // Don't trigger while typing in an input, textarea, or select
    const tag = (e.target as HTMLElement).tagName.toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;

    const idx = activities.findIndex((a) => a.id === actId);
    if (idx === -1) return;

    if (e.key === "ArrowRight" && idx < activities.length - 1) {
      navigate(`/activities/${activities[idx + 1].id}`);
    } else if (e.key === "ArrowLeft" && idx > 0) {
      navigate(`/activities/${activities[idx - 1].id}`);
    }
  };

  window.addEventListener("keydown", handleKeyDown);
  return () => window.removeEventListener("keydown", handleKeyDown);
}, [activities, actId, navigate]);
```

- [ ] **Step 5: Build to verify no TypeScript errors**

```bash
cd /home/tim/projects/runscribe/frontend && npm run build 2>&1 | grep -E "^.*error TS" | head -20
```

Expected: no output (zero TypeScript errors)

- [ ] **Step 6: Manual smoke test**

1. Start the app (`docker compose up` or local dev server)
2. Navigate to any activity detail page (e.g. `/activities/102`)
3. Press `→` — should navigate to the next older activity
4. Press `←` — should navigate back
5. Press `→` repeatedly until reaching the oldest activity — should stop with no error
6. Press `←` repeatedly until reaching the newest activity — should stop with no error
7. Click into the shoe dropdown and press `→` — should NOT navigate (input has focus)

- [ ] **Step 7: Commit**

```bash
cd /home/tim/projects/runscribe && git add frontend/src/pages/ActivityDetail.tsx && git commit -m "feat: arrow key navigation between activities on detail page

ArrowRight → older activity, ArrowLeft → newer. Skips when an input
element has focus to avoid conflicts with the shoe dropdown.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Chunk 2: Build and Deploy

### Task 2: Build and push updated image

- [ ] **Step 1: Build**

```bash
cd /home/tim/projects/runscribe && docker compose build
```

- [ ] **Step 2: Push**

```bash
docker compose push
```

- [ ] **Step 3: Deploy on coruscant**

```bash
sudo docker compose pull && sudo docker compose up -d runscribe
```
