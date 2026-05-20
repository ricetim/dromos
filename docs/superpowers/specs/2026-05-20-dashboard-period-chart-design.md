# Dashboard Period-Aware Volume Chart — Design Spec

**Date:** 2026-05-20
**Status:** Approved

## Goal

Make the dashboard period toggle drive the volume chart, not just the StatCards. Replace today's hard-coded "Last 7 Days" chart with a chart whose bucketing follows the selected period: daily for *Last 7 days* and *Month*, weekly for *Year*. Use calendar boundaries for *Month* and *Year* (May 1–31, Jan 1–Dec 31), not rolling windows.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Period boundaries | Calendar everywhere (chart + StatCards) | Matches "entire month / entire year" wording; chart total === StatCards Distance by construction |
| Buttons | `Last 7 days · Month · Year` (drop "All") | "All" added complexity with no clear chart; lifetime totals are rarely viewed |
| Year bucketing | Sunday-start weekly bars (~52–53) | Matches existing 7-day chart's Sun…Sat labels |
| Future days/weeks | Render as empty bars | Stable chart shape through the month; signals progress visually |
| Computation locus | Backend builder writes pre-bucketed data into `dashboard.json` | Matches static-content preference; eliminates client-side drift between chart total and StatCards |

## Architecture

```
Activity write
    │
    ▼
backend/app/services/builder.py::_rebuild_dashboard()
    │  Computes for each period in {last_7_days, month, year}:
    │    • summary[period]   — count, total_distance_km, etc. (calendar-bound)
    │    • volume[period]    — buckets[] + total_km
    ▼
data/static/dashboard.json
    ▼
nginx /static/  (immutable, busted on rebuild)
    ▼
Frontend
    • api/client.ts   getStatsSummary(period), getVolumeBuckets(period)
    • Dashboard.tsx   <VolumeChart period={period}/>
```

**Invariant:** `volume[period].total_km === summary[period].total_distance_km` — both produced from the same activity filter in the same builder pass.

## Backend Changes

### `backend/app/services/builder.py::_rebuild_dashboard`

Add a helper that produces both summary and volume for a given period:

```python
def _compute_period_data(acts: list[Activity], period: str, today: date) -> tuple[dict, dict]:
    if period == "last_7_days":
        start, end = today - timedelta(days=6), today
        bucket_size = "day"
    elif period == "month":
        start = today.replace(day=1)
        end   = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        bucket_size = "day"
    elif period == "year":
        start = date(today.year, 1, 1)
        end   = date(today.year, 12, 31)
        bucket_size = "week"

    in_period = [a for a in acts if start <= a.started_at.date() <= end]

    summary = {
        "period": period,
        "count": len(in_period),
        "total_distance_km": round(sum(a.distance_m for a in in_period) / 1000, 2),
        "total_duration_s":  sum(a.duration_s for a in in_period),
        "total_elevation_m": round(sum(a.elevation_gain_m for a in in_period), 1),
        "avg_pace_s_per_km": _weighted_avg_pace(in_period),
    }

    buckets = (_bucket_by_day if bucket_size == "day"
               else _bucket_by_week_sun_start)(in_period, start, end)

    volume = {"buckets": buckets, "total_km": summary["total_distance_km"]}
    return summary, volume
```

The function is called three times (one per period) and results merged into `dashboard.json`:

```json
{
  "summary": {
    "last_7_days": { ... },
    "month":       { ... },
    "year":        { ... }
  },
  "volume": {
    "last_7_days": { "buckets": [{"date":"2026-05-14","label":"Thu","km":5.2}, ...7],
                     "total_km": 32.1 },
    "month":       { "buckets": [{"date":"2026-05-01","label":"1","km":0}, ...31],
                     "total_km": 78.4 },
    "year":        { "buckets": [{"date":"2025-12-28","label":"Jan 1","km":21.5}, ...53],
                     "total_km": 612.8 }
  },
  ...existing fields (training_load, vdot, personal_bests)
}
```

### Bucket label conventions

| Period | `label` |
|---|---|
| `last_7_days` | day-of-week short: `Sun Mon Tue Wed Thu Fri Sat` |
| `month` | day-of-month: `"1"`…`"31"` |
| `year` | label of first in-year day in that week: `"Jan 1"`, `"Jan 8"`, … |

For the year view, the first bucket's `date` is the **Sunday on or before** Jan 1 of the current year — but only mileage from Jan 1 onward counts in that bucket's `km`. (e.g., 2026: Jan 1 = Thu; the first weekly bucket starts Sun Dec 28 but only sums activities on Jan 1–3.)

### `backend/app/routers/stats.py::get_summary`

- Replace the regex `^(week|month|year|all)$` with `^(last_7_days|month|year)$`.
- Body delegates to `dashboard.json` (already does via static read). Rolling logic is removed.

### Tests

`backend/tests/test_builder.py` — three new tests with a frozen `today`:
1. `test_volume_last_7_days_buckets_count_and_total` — 7 daily bars; `sum(bucket.km) == summary.total_distance_km`.
2. `test_volume_month_includes_all_calendar_days` — bar count equals days in current month; future days have `km=0`; the sum matches the summary.
3. `test_volume_year_sunday_start_weeks` — first bucket date is the Sunday ≤ Jan 1; bucket count is 52 or 53; total matches summary.

`backend/tests/test_stats.py` — update existing summary tests to use `last_7_days`; drop the `all` and `week` tests.

## Frontend Changes

### `frontend/src/pages/Dashboard.tsx`

```tsx
const PERIODS = ["last_7_days", "month", "year"] as const;
type Period = (typeof PERIODS)[number];

const PERIOD_LABELS: Record<Period, string> = {
  last_7_days: "Last 7 days",
  month: "Month",
  year: "Year",
};
```

- Button row (lines 370–385) iterates `PERIODS` and displays `PERIOD_LABELS[p]`.
- Initial state: `last_7_days`.
- Delete `Last7Days` component (lines 287–337).
- Replace `<Last7Days acts={allActs} />` (line 400) with `<VolumeChart period={period} />`.

### New `VolumeChart` component (same file)

```tsx
function VolumeChart({ period }: { period: Period }) {
  const { system } = useUnits();
  const { data } = useQuery({
    queryKey: ["volume", period],
    queryFn: () => getVolumeBuckets(period),
    staleTime: Infinity,
  });
  if (!data) return null;

  const distUnit = system === "imperial" ? "mi" : "km";
  const toDisplay = (km: number) =>
    system === "imperial" ? +(km * 0.621371).toFixed(1) : +km.toFixed(1);

  const rows = data.buckets.map((b) => ({ label: b.label, dist: toDisplay(b.km) }));
  const total = toDisplay(data.total_km);
  const gap = period === "year" ? "8%" : period === "month" ? "12%" : "25%";

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-700">{PERIOD_LABELS[period]}</h2>
        <span className="text-sm font-bold text-gray-800">{total} {distUnit}</span>
      </div>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }} barCategoryGap={gap}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
          <YAxis  tick={{ fontSize: 10 }} width={36} unit={` ${distUnit}`} />
          <Tooltip contentStyle={{ fontSize: 12 }}
                   formatter={(v: number) => [`${v} ${distUnit}`, "Distance"]} />
          <Bar dataKey="dist" fill="#3b82f6" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

Differences from old `Last7Days`:
- Height 110 → 140 (more bars on month/year views).
- Renders even when all bars are 0 (toggle UI consistency).
- `interval="preserveStartEnd"` lets Recharts thin x-axis labels on the year view.

### `frontend/src/api/client.ts`

```ts
export const getStatsSummary = (period: "last_7_days" | "month" | "year" = "last_7_days") =>
  _fetchJson("/static/dashboard.json").then((d) => d.summary[period]);

export const getVolumeBuckets = (period: "last_7_days" | "month" | "year") =>
  _fetchJson("/static/dashboard.json").then((d) => d.volume[period]);
```

### `frontend/src/App.tsx`

Update prefetch keys (App.tsx:32–33) from `week`/`month` to `last_7_days`/`month`/`year`. Both `stats-summary` and `volume` queries share the same `dashboard.json` HTTP request.

## Edge Cases

| Case | Behavior |
|---|---|
| Today = Jan 1 | Year view shows 52–53 mostly-empty bars |
| Year starts mid-week | First weekly bar's `date` is Sun ≤ Jan 1; `label` is the first in-year date; only in-year mileage counts |
| Empty DB | All three views render zero-bars + `"0 km"` total |
| Activity stored at 23:59 local but UTC next-day | Backend uses `started_at.date()` in UTC (storage convention) — same as the rest of the app |
| Imperial units | Backend stores km; frontend converts on render — unchanged from current convention |
| Rebuild lag after upload | Existing `_invalidate_*` invalidation hooks already trigger React Query refetch |

## Deployment

1. Local: rebuild fires on next activity write or backend restart (`_startup_rebuild` always runs globals). Verify at `http://192.168.0.233:5173/`.
2. Commit + push to GitHub.
3. Build & push Docker image.
4. Coruscant: `docker compose down && docker compose up -d` (never `restart`).
5. Startup rebuild populates new `volume` field.

## Out of Scope (Deliberate)

- No backwards-compat shim for `week` / `all` period keys.
- No precomputed imperial units (frontend converts).
- No new lifetime-totals widget; if needed later, a separate feature.
