# Shoe Mileage Timeline Chart Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cumulative-mileage line chart to the Gear page that shows every shoe's lifetime wear over time, with a year-window dropdown. All chart data is precomputed server-side and written to `shoes.json`.

**Architecture:** Extend the existing `_rebuild_shoes` function in `backend/app/services/builder.py` to write a `timeline` and `years` array per shoe into `shoes.json`. The frontend `Gear.tsx` page consumes those fields directly via the existing `getShoes()` static-fetch — no client-side aggregation, no new endpoints, no new triggers (every mutation that affects shoe-to-activity links already calls `_rebuild_shoes`).

**Tech Stack:** Python 3.10, SQLModel, FastAPI, React 18, TypeScript, Recharts, Tailwind, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-05-04-shoe-mileage-timeline-chart-design.md`

---

## File Structure

**Modified:**
- `backend/app/services/builder.py` — extend `_rebuild_shoes` (around line 327) to compute timelines and years per shoe.
- `backend/tests/test_builder.py` — add tests for the timeline output.
- `frontend/src/pages/Gear.tsx` — add `Timeline` chart component, year dropdown, type updates.

**No new files.** The chart component is small enough to live inline in `Gear.tsx`. If it grows past ~120 LoC, split it later — premature for now.

---

## Task 1: Add timeline + years computation to `_rebuild_shoes`

**Files:**
- Modify: `backend/app/services/builder.py:327-351` (the existing `_rebuild_shoes` function)
- Test: `backend/tests/test_builder.py` (append)

This is the core backend change. The existing function does one `sum(distance_m)` aggregate per shoe; we replace it with one ordered query, walk the rows, and build per-shoe timelines.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_builder.py`:

```python
def test_rebuild_shoes_writes_timeline(session, tmp_path):
    """Each shoe's timeline lists cumulative km in chronological order."""
    from app.services.builder import _rebuild_shoes
    from app.models import ActivityShoe

    shoe = Shoe(name="Endorphin", retirement_threshold_km=800.0)
    session.add(shoe)
    session.flush()

    # Two activities on different days, intentionally inserted out of order
    a2 = Activity(
        source="manual_upload",
        started_at=datetime(2025, 6, 10, tzinfo=timezone.utc),
        distance_m=8000.0, duration_s=2400, elevation_gain_m=50.0, sport_type="run",
    )
    a1 = Activity(
        source="manual_upload",
        started_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
        distance_m=5000.0, duration_s=1800, elevation_gain_m=20.0, sport_type="run",
    )
    session.add_all([a1, a2])
    session.flush()
    session.add_all([
        ActivityShoe(activity_id=a1.id, shoe_id=shoe.id),
        ActivityShoe(activity_id=a2.id, shoe_id=shoe.id),
    ])
    session.commit()

    _rebuild_shoes(session, tmp_path)
    data = json.loads((tmp_path / "shoes.json").read_text())
    assert len(data) == 1
    s = data[0]

    assert s["timeline"] == [
        {"date": "2025-01-05", "cumulative_km": 5.0},
        {"date": "2025-06-10", "cumulative_km": 13.0},
    ]
    assert s["years"] == [2025]
    # Existing field still correct
    assert s["total_distance_km"] == 13.0


def test_rebuild_shoes_timeline_empty_when_no_activities(session, tmp_path):
    from app.services.builder import _rebuild_shoes
    session.add(Shoe(name="Unused", retirement_threshold_km=800.0))
    session.commit()

    _rebuild_shoes(session, tmp_path)
    data = json.loads((tmp_path / "shoes.json").read_text())
    assert data[0]["timeline"] == []
    assert data[0]["years"] == []
    assert data[0]["total_distance_km"] == 0.0


def test_rebuild_shoes_timeline_distinct_years(session, tmp_path):
    from app.services.builder import _rebuild_shoes
    from app.models import ActivityShoe

    shoe = Shoe(name="Multi", retirement_threshold_km=800.0)
    session.add(shoe)
    session.flush()
    for year, dist in [(2024, 4000.0), (2024, 3000.0), (2025, 2000.0), (2026, 1000.0)]:
        a = Activity(
            source="manual_upload",
            started_at=datetime(year, 3, 1, tzinfo=timezone.utc),
            distance_m=dist, duration_s=1800, elevation_gain_m=10.0, sport_type="run",
        )
        session.add(a)
        session.flush()
        session.add(ActivityShoe(activity_id=a.id, shoe_id=shoe.id))
    session.commit()

    _rebuild_shoes(session, tmp_path)
    s = json.loads((tmp_path / "shoes.json").read_text())[0]
    assert s["years"] == [2024, 2025, 2026]
    # Cumulative grows monotonically
    cums = [pt["cumulative_km"] for pt in s["timeline"]]
    assert cums == sorted(cums)
    assert cums[-1] == 10.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest backend/tests/test_builder.py::test_rebuild_shoes_writes_timeline -xvs
```

Expected: FAIL — `KeyError: 'timeline'` (the field doesn't exist yet).

- [ ] **Step 3: Implement the change**

Replace the body of `_rebuild_shoes` (currently at `backend/app/services/builder.py:327-351`) with:

```python
def _rebuild_shoes(session: Session, static_dir: Path) -> None:
    from app.models import Activity, ActivityShoe, Shoe

    shoes = session.exec(select(Shoe)).all()

    # One ordered query: shoe_id, started_at, distance_m for every linked activity.
    rows = session.exec(
        select(ActivityShoe.shoe_id, Activity.started_at, Activity.distance_m)
        .join(Activity, ActivityShoe.activity_id == Activity.id)
        .order_by(ActivityShoe.shoe_id, Activity.started_at)
    ).all()

    # Walk rows once, building per-shoe cumulative timelines.
    timelines: dict[int, list[dict]] = defaultdict(list)
    years: dict[int, set[int]] = defaultdict(set)
    activity_ids: dict[int, list[int]] = defaultdict(list)

    # We need activity_ids too — keep a separate query (lightweight).
    link_rows = session.exec(
        select(ActivityShoe.shoe_id, ActivityShoe.activity_id)
    ).all()
    for shoe_id, act_id in link_rows:
        activity_ids[shoe_id].append(act_id)

    cum_m: dict[int, float] = defaultdict(float)
    for shoe_id, started_at, distance_m in rows:
        cum_m[shoe_id] += distance_m or 0.0
        timelines[shoe_id].append({
            "date": started_at.date().isoformat(),
            "cumulative_km": round(cum_m[shoe_id] / 1000, 1),
        })
        years[shoe_id].add(started_at.year)

    result = []
    for shoe in shoes:
        result.append({
            **shoe.model_dump(),
            "total_distance_km": round(cum_m[shoe.id] / 1000, 1),
            "activity_ids": sorted(activity_ids.get(shoe.id, []), reverse=True),
            "timeline": timelines.get(shoe.id, []),
            "years": sorted(years.get(shoe.id, [])),
        })
    _write_json(static_dir / "shoes.json", result)
```

Notes for the implementer:
- `defaultdict` is already imported at the top of the file (line 11).
- `Activity`, `ActivityShoe`, `Shoe` are imported inside the function (existing pattern — keeps the import scope tight).
- `started_at` is a naive `datetime` in this codebase; `.date()` works on either naive or aware.
- The previous `func.sum(...)` per-shoe query is replaced by walking `cum_m` — same correctness, fewer queries.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest backend/tests/test_builder.py -xvs
```

Expected: all builder tests pass, including the three new ones. The existing `test_rebuild_globals_writes_all_files` should still pass (the `total_distance_km` and `activity_ids` fields are unchanged).

- [ ] **Step 5: Run the full backend suite to confirm no regression**

```bash
python3 -m pytest backend/ -x -q
```

Expected: 61 passed (was 58; +3 new).

If you see `PermissionError: [Errno 13] Permission denied: '/data'`: that's a pre-existing environment issue when `app.main` is imported outside Docker. The `tiles.py` import tries to `mkdir /data`. Set `DATA_DIR=/tmp/runscribe-test python3 -m pytest …` to work around it locally.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/builder.py backend/tests/test_builder.py
git commit -m "feat: precompute per-shoe cumulative-mileage timeline in shoes.json"
```

---

## Task 2: Frontend types & data loading

**Files:**
- Modify: `frontend/src/pages/Gear.tsx:8-17` (the local `Shoe` interface)

The shape change is small. We do this first so the chart task in Task 3 has the right types.

- [ ] **Step 1: Add timeline + years to the `Shoe` interface**

Replace the existing interface (currently `Gear.tsx:8-17`):

```ts
interface TimelinePoint {
  date: string;          // "YYYY-MM-DD"
  cumulative_km: number;
}

interface Shoe {
  id: number;
  name: string;
  brand: string | null;
  retired: boolean;
  notes: string | null;
  retirement_threshold_km: number;
  total_distance_km: number;
  activity_ids?: number[];
  timeline: TimelinePoint[];
  years: number[];
}
```

- [ ] **Step 2: Verify TypeScript still compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Gear.tsx
git commit -m "chore: extend Shoe type with timeline and years"
```

---

## Task 3: ShoeTimelineChart component + year dropdown in Gear.tsx

**Files:**
- Modify: `frontend/src/pages/Gear.tsx` (add component, dropdown, render)

This is the bulk of the frontend change. Keep it inside `Gear.tsx` as agreed.

- [ ] **Step 1: Add Recharts + config imports**

At the top of `frontend/src/pages/Gear.tsx`, extend the existing imports:

```ts
import { useMemo, useState } from "react";   // useMemo is new
// ...existing imports...
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, Legend,
} from "recharts";
import { CHART_COLORS } from "../config";
```

Verify `CHART_COLORS` exists in `config.ts`. If not, fall back to a local array of ~10 hex colors at the top of `Gear.tsx`.

- [ ] **Step 2: Add `ShoeTimelineChart` component above the `Gear` default export**

Insert this component definition just above `export default function Gear()`:

```tsx
type YearOption = "all" | number;

function ShoeTimelineChart({
  shoes,
  year,
}: {
  shoes: Shoe[];
  year: YearOption;
}) {
  const { fmtShoe, system } = useUnits();
  const yUnit = system === "imperial" ? "mi" : "km";
  const toDisplay = (km: number) =>
    system === "imperial" ? km / KM_PER_MI : km;

  // For each shoe, build the data array for THIS year window.
  // Strategy: emit { date, [shoeName]: cumulative_display_value } points.
  // Recharts merges by `date` automatically when we pass one combined array.
  const chartData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string>>();

    for (const shoe of shoes) {
      if (!shoe.timeline.length) continue;

      let entries = shoe.timeline;
      if (year !== "all") {
        const startStr = `${year}-01-01`;
        const endStr = `${year}-12-31`;
        const inWindow = entries.filter(
          (p) => p.date >= startStr && p.date <= endStr
        );
        if (inWindow.length === 0) {
          // No activities this year — skip shoe entirely.
          continue;
        }
        // Synthetic carry-over point at Jan 1 if shoe had prior mileage.
        const prior = entries.filter((p) => p.date < startStr);
        if (prior.length) {
          entries = [
            { date: startStr, cumulative_km: prior[prior.length - 1].cumulative_km },
            ...inWindow,
          ];
        } else {
          entries = inWindow;
        }
      }

      for (const pt of entries) {
        const row = byDate.get(pt.date) ?? { date: pt.date };
        row[shoe.name] = toDisplay(pt.cumulative_km);
        byDate.set(pt.date, row);
      }
    }

    return Array.from(byDate.values()).sort((a, b) =>
      String(a.date).localeCompare(String(b.date))
    );
  }, [shoes, year, system]);

  // Build the list of shoes that actually appear in chartData (so the legend
  // doesn't list shoes that have no points in the selected year).
  const visibleShoes = useMemo(() => {
    const names = new Set<string>();
    for (const row of chartData) {
      for (const k of Object.keys(row)) if (k !== "date") names.add(k);
    }
    return shoes.filter((s) => names.has(s.name));
  }, [shoes, chartData]);

  if (chartData.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 text-center text-sm text-gray-400">
        No mileage to chart {year !== "all" ? `for ${year}` : "yet"}.
      </div>
    );
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: "#6b7280" }}
            minTickGap={32}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#6b7280" }}
            label={{ value: yUnit, position: "insideLeft", angle: -90, offset: 10, fontSize: 11, fill: "#9ca3af" }}
          />
          <Tooltip
            formatter={(value: number, name: string) => [fmtShoe(
              system === "imperial" ? Number(value) * KM_PER_MI : Number(value)
            ), name]}
            labelFormatter={(label) => label}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {visibleShoes.map((shoe, idx) => (
            <Line
              key={shoe.id}
              type="monotone"
              dataKey={shoe.name}
              stroke={CHART_COLORS[idx % CHART_COLORS.length]}
              strokeWidth={2}
              strokeDasharray={shoe.retired ? "4 2" : undefined}
              strokeOpacity={shoe.retired ? 0.55 : 1}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
          {year === "all" &&
            visibleShoes.map((shoe, idx) => (
              <ReferenceLine
                key={`ref-${shoe.id}`}
                y={toDisplay(shoe.retirement_threshold_km)}
                stroke={CHART_COLORS[idx % CHART_COLORS.length]}
                strokeOpacity={0.25}
                strokeDasharray="2 4"
                ifOverflow="extendDomain"
              />
            ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

Notes:
- `connectNulls` lets the line span dates where a *different* shoe was the active one (i.e., this shoe didn't have a data point that day).
- `isAnimationActive={false}` keeps the chart snappy on year-dropdown changes.
- `ReferenceLine` per shoe is gated to "All time" since per-year wear rarely reaches the threshold.

- [ ] **Step 3: Add year-dropdown state inside the `Gear` component**

After the existing `useState` lines for `showForm` and `form` (around `Gear.tsx:35-36`), add:

```ts
const [yearFilter, setYearFilter] = useState<YearOption>("all");

const yearOptions = useMemo<number[]>(() => {
  const all = new Set<number>();
  for (const s of shoes) for (const y of s.years) all.add(y);
  return Array.from(all).sort((a, b) => b - a);  // descending
}, [shoes]);
```

(`shoes` is the existing `useQuery` result.)

- [ ] **Step 4: Render the chart + dropdown**

In the JSX, just below the page header `<div className="flex items-center justify-between flex-wrap gap-2">…</div>` (which ends around `Gear.tsx:81`) and **above** the `{showForm && …}` block, insert:

```tsx
{shoes.length > 0 && (
  <div className="space-y-2">
    <div className="flex items-center justify-between">
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
        Mileage over time
      </h2>
      <select
        value={String(yearFilter)}
        onChange={(e) =>
          setYearFilter(e.target.value === "all" ? "all" : Number(e.target.value))
        }
        className="text-xs border border-gray-200 rounded px-2 py-1 bg-white text-gray-700"
      >
        <option value="all">All time</option>
        {yearOptions.map((y) => (
          <option key={y} value={y}>{y}</option>
        ))}
      </select>
    </div>
    <ShoeTimelineChart shoes={shoes} year={yearFilter} />
  </div>
)}
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Smoke-test in the browser**

```bash
docker compose down && docker compose up -d --build
```

Open the app, navigate to **Gear**, and verify:
- A chart appears above the active-shoe list (only when at least one shoe exists).
- One line per shoe; retired shoes are dashed and faded.
- Year dropdown shows "All time" plus every year that has activity.
- Selecting a year filters the chart; shoes with prior mileage enter the chart at their Jan-1 carry-over height.
- Hovering a line shows shoe name + cumulative mileage.
- Toggling units (km/mi) flips the Y-axis values correctly.
- Retirement-threshold dashed reference lines appear in "All time" only.

If the dev environment is faster, `cd frontend && npm run dev` works for iteration; the full `docker compose` round-trip is only needed to verify the static-rebuild trigger end-to-end.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Gear.tsx
git commit -m "feat(gear): cumulative shoe-mileage chart with year filter"
```

---

## Task 4: End-to-end verification

- [ ] **Step 1: Confirm the rebuild fires on every relevant mutation**

These code paths already call `_rebuild_shoes` indirectly (via `bg_rebuild_after_*`) — confirm by reading them:

- `backend/app/routers/activities.py` — `upload_fit` → `bg_rebuild_after_upload`
- `backend/app/routers/activities.py` — `delete_activity` → `bg_rebuild_after_delete`
- `backend/app/routers/activities.py` — `update_activity` (PATCH notes/name/rpe) → `bg_rebuild_after_activity_update`
- `backend/app/routers/activities.py` — `update_activity_shoe` → `_rebuild_shoes` (direct) + `bg_rebuild_after_activity_update`
- `backend/app/routers/shoes.py` — create/update shoe → check it triggers `bg_rebuild_globals` or `_rebuild_shoes`. If not, add a trigger.

- [ ] **Step 2: If `shoes.py` is missing a trigger, add it**

Read `backend/app/routers/shoes.py`. If `create_shoe` or `update_shoe` does not call any rebuild function, add `background_tasks.add_task(bg_rebuild_globals)` (or just `_rebuild_shoes` directly, mirroring the activity-shoe router). This is the only path where a newly-added shoe would otherwise have stale `timeline`/`years` data.

If a trigger is already present, skip this step.

- [ ] **Step 3: Run final test sweep**

```bash
python3 -m pytest backend/ -q
cd frontend && npx tsc --noEmit && cd ..
```

Both clean.

- [ ] **Step 4: Final commit (if shoes.py needed a fix)**

```bash
git add backend/app/routers/shoes.py
git commit -m "fix: rebuild shoes.json on shoe create/update"
```

---

## Acceptance Checklist (mirrors the spec)

- [ ] `shoes.json` contains `timeline` (chronological) and `years` (sorted ascending) for every shoe.
- [ ] `total_distance_km` still equals `timeline[-1].cumulative_km` (or 0 for shoes with no activities).
- [ ] Timeline rebuilds on activity upload, delete, update, shoe-assignment change, and shoe create/update.
- [ ] Chart renders one line per shoe; retired shoes are dashed (`4 2`) and faded (opacity 0.55).
- [ ] Year dropdown defaults to "All time" and shows every distinct year from any shoe's history, descending.
- [ ] In year-scoped view, shoes with prior mileage enter at their carry-over `cumulative_km` (synthetic Jan-1 point).
- [ ] Retirement-threshold reference lines appear only in "All time".
- [ ] Tooltip shows shoe name + cumulative distance in the active unit.
- [ ] Units toggle (mi/km) works on the Y-axis and tooltip.
- [ ] All backend tests pass; frontend `tsc` is clean.
