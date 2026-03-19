# Activity Keyboard Navigation — Design Spec

**Date:** 2026-03-19

## Summary

Add arrow key navigation on the ActivityDetail page. Pressing → advances to the chronologically older activity; pressing ← goes to the newer one.

## Behavior

- `ArrowRight` → navigate to the next older activity (index + 1 in newest-first list)
- `ArrowLeft` → navigate to the next newer activity (index - 1 in newest-first list)
- At boundaries (first or last activity): do nothing silently
- Does not fire when an input, textarea, or select element has focus (prevents conflict with the notes field and shoe dropdown)
- Listener is registered on `window` and cleaned up on component unmount

## Implementation

All changes in `frontend/src/pages/ActivityDetail.tsx`:

1. Add `useNavigate` from `react-router-dom` (may already be imported)
2. Add `useQuery` for activities list via `getActivities()` — TanStack Query caches this so it's free after the first visit to the list page
3. Add a `useEffect` that registers a `keydown` listener:
   - Find the current activity's index in the sorted list (newest-first)
   - `ArrowRight`: if `index < activities.length - 1`, navigate to `activities[index + 1].id`
   - `ArrowLeft`: if `index > 0`, navigate to `activities[index - 1].id`
   - Skip if `document.activeElement` is an input, textarea, or select

## Files Changed

- `frontend/src/pages/ActivityDetail.tsx` — only file modified
