# Dashboard Period-Aware Volume Chart Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard period toggle drive the volume chart in addition to the StatCards. Replace today's hard-coded "Last 7 Days" chart with one that switches between three calendar-bound views: *Last 7 days* (7 daily bars), *Month* (1 bar per day of current calendar month), and *Year* (~53 Sunday-start weekly bars).

**Architecture:** Backend builder precomputes both summaries and bucketed volume data into `dashboard.json` for each of the three period keys (`last_7_days`, `month`, `year`). Frontend reads pre-bucketed data — zero client-side aggregation. The chart total is identical to the StatCards Distance value by construction (both come from the same backend filter).

**Tech Stack:** Python 3.10 + FastAPI + SQLModel (backend); React 18 + TypeScript + Vite + Recharts (frontend); pytest for backend tests; manual browser verification for frontend (project has no frontend test suite).

**Spec:** `docs/superpowers/specs/2026-05-20-dashboard-period-chart-design.md`

---

## Background context every implementer needs

- All stats reads in this app are **static-first**: nginx serves precomputed `/data/static/*.json`. Backend Python code only runs on writes; the rebuild functions live in `backend/app/services/builder.py` and are triggered by activity-mutation routers.
- Today, `_rebuild_dashboard` calls `app.routers.stats.get_summary(...)` directly as a Python function (not over HTTP) — see `backend/app/services/builder.py:293–301`. We're moving the period logic out of the stats router into the builder so calendar boundaries live in one place.
- The HTTP `/api/stats/summary` endpoint exists but is **not consumed by the frontend** (frontend reads `/static/dashboard.json` instead). Its regex still needs updating for hygiene, but no live caller uses it.
- The frontend has **no test suite** (per recent commits). Frontend tasks rely on manual browser verification at `http://192.168.0.233:5173/`.
- Python 3.10 is the target. Use `python3 -m pytest` for tests (not `pytest` directly) — system has multiple Python versions installed.
- After Docker rebuilds: **always** `docker compose down && docker compose up -d`. Never `restart` (project memory: digest-pinning bug with restart).

## Files touched

| File | Action | Responsibility |
|---|---|---|
| `backend/app/services/builder.py` | Modify | Add bucketing helpers + period-data computation; rewrite `_rebuild_dashboard` to emit new `summary` + `volume` shape |
| `backend/app/routers/stats.py` | Modify | Update `get_summary` regex to accept `last_7_days|month|year` (drop `week|all`); body unchanged since frontend doesn't use it |
| `backend/tests/test_builder.py` | Modify | Add tests for bucketing helpers + `_rebuild_dashboard` new shape |
| `frontend/src/api/client.ts` | Modify | Update `getStatsSummary` period type; add `getVolumeBuckets` |
| `frontend/src/pages/Dashboard.tsx` | Modify | Replace `Last7Days` with `VolumeChart`; update `PERIODS` array + labels |
| `frontend/src/App.tsx` | Modify | Update prefetch keys to use new period names |

---

## Chunk 1: Backend bucketing helpers (TDD)

### Task 1: Daily bucket helper

**Files:**
- Modify: `backend/app/services/builder.py` (add helpers near top, after `_downsample`)
- Modify: `backend/tests/test_builder.py` (add tests near end)

- [ ] **Step 1: Write the failing test for daily bucketing — last 7 days**

Append to `backend/tests/test_builder.py`:

```python
# ──────────────────────────────────────────────────────────────────────────
# Period volume bucketing
# ──────────────────────────────────────────────────────────────────────────

from datetime import date as _date
from app.services.builder import _bucket_by_day, _bucket_by_week_sun_start, _compute_period_data


def _make_act(session, started_at_date, distance_m=5000.0):
    """Helper: create a minimal Activity on a given date."""
    a = Activity(
        source="manual_upload",
        started_at=datetime(started_at_date.year, started_at_date.month, started_at_date.day,
                            12, 0, tzinfo=timezone.utc),
        distance_m=distance_m,
        duration_s=1800,
        elevation_gain_m=10.0,
        sport_type="run",
    )
    session.add(a)
    session.commit()
    return a


def test_bucket_by_day_last_7_days_uses_weekday_labels(session):
    """7-day view: 7 daily buckets labeled Sun..Sat in chronological order."""
    today = _date(2026, 5, 20)  # Wednesday
    start = today - timedelta(days=6)  # Thursday May 14
    end = today

    # Create one 5km run on Saturday May 16
    _make_act(session, _date(2026, 5, 16))
    acts = session.exec(select(Activity)).all()

    buckets = _bucket_by_day(acts, start, end, label_style="weekday")

    assert len(buckets) == 7
    assert buckets[0] == {"date": "2026-05-14", "label": "Thu", "km": 0.0}
    assert buckets[1] == {"date": "2026-05-15", "label": "Fri", "km": 0.0}
    assert buckets[2] == {"date": "2026-05-16", "label": "Sat", "km": 5.0}
    assert buckets[6] == {"date": "2026-05-20", "label": "Wed", "km": 0.0}


def test_bucket_by_day_month_uses_day_of_month_labels(session):
    """Month view: bucket labels are day-of-month strings ('1'..'31')."""
    start = _date(2026, 5, 1)
    end = _date(2026, 5, 31)

    _make_act(session, _date(2026, 5, 10), distance_m=3000.0)
    _make_act(session, _date(2026, 5, 10), distance_m=2000.0)  # 2 runs same day
    acts = session.exec(select(Activity)).all()

    buckets = _bucket_by_day(acts, start, end, label_style="day_of_month")

    assert len(buckets) == 31
    assert buckets[0] == {"date": "2026-05-01", "label": "1", "km": 0.0}
    assert buckets[9] == {"date": "2026-05-10", "label": "10", "km": 5.0}  # sum of both runs
    assert buckets[30] == {"date": "2026-05-31", "label": "31", "km": 0.0}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tim/projects/dromos/backend && python3 -m pytest tests/test_builder.py::test_bucket_by_day_last_7_days_uses_weekday_labels tests/test_builder.py::test_bucket_by_day_month_uses_day_of_month_labels -v
```

Expected: `ImportError: cannot import name '_bucket_by_day'` — or the function doesn't exist yet.

- [ ] **Step 3: Implement `_bucket_by_day` in `backend/app/services/builder.py`**

Insert after the `_downsample` function (around line 75, before `def rebuild_activity`):

```python
# ──────────────────────────────────────────────────────────────────────────
# Period volume bucketing helpers
# ──────────────────────────────────────────────────────────────────────────

_WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _bucket_by_day(acts, start: date, end: date, label_style: str) -> list[dict]:
    """
    One bucket per calendar day in [start, end] inclusive.

    label_style:
      - "weekday"       — "Sun".."Sat" (used by last_7_days view)
      - "day_of_month"  — "1".."31"    (used by month view)

    Returns a chronologically ordered list of {date, label, km} dicts.
    Activities outside [start, end] are ignored. Future days have km=0.
    """
    n_days = (end - start).days + 1
    by_date: dict[date, float] = {}
    for a in acts:
        d = a.started_at.date()
        if start <= d <= end:
            by_date[d] = by_date.get(d, 0.0) + a.distance_m

    buckets = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        if label_style == "weekday":
            label = _WEEKDAY_SHORT[d.weekday()]
        elif label_style == "day_of_month":
            label = str(d.day)
        else:
            raise ValueError(f"unknown label_style: {label_style}")
        buckets.append({
            "date": d.isoformat(),
            "label": label,
            "km": round(by_date.get(d, 0.0) / 1000.0, 2),
        })
    return buckets
```

Note: Python's `date.weekday()` returns 0=Monday, so `_WEEKDAY_SHORT[0] = "Mon"`. The test expects `Thu` for `2026-05-14` — verify with `date(2026,5,14).weekday()` (returns 3, → `"Thu"` ✓).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tim/projects/dromos/backend && python3 -m pytest tests/test_builder.py::test_bucket_by_day_last_7_days_uses_weekday_labels tests/test_builder.py::test_bucket_by_day_month_uses_day_of_month_labels -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/builder.py backend/tests/test_builder.py
git commit -m "feat(builder): add daily bucketing helper for volume chart"
```

---

### Task 2: Weekly bucket helper (Sunday-start)

**Files:**
- Modify: `backend/app/services/builder.py`
- Modify: `backend/tests/test_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_builder.py`:

```python
def test_bucket_by_week_sun_start_2026(session):
    """
    Year 2026 starts on Thursday Jan 1.
    The first weekly bucket's date is Sun Dec 28, 2025 (Sunday on or before Jan 1).
    Its label is "Jan 1" (first in-year date in that week).
    Only mileage from Jan 1 onward counts (Dec 28-31 runs are ignored).
    """
    start = _date(2026, 1, 1)   # Thu
    end = _date(2026, 12, 31)  # Thu

    # Run on Dec 29 2025 (Mon, OUT of year window) — should NOT count
    _make_act(session, _date(2025, 12, 29), distance_m=10000.0)
    # Run on Jan 2 2026 (Fri, in first weekly bucket) — SHOULD count
    _make_act(session, _date(2026, 1, 2), distance_m=8000.0)
    # Run on Jan 11 2026 (Sun, START of second bucket)
    _make_act(session, _date(2026, 1, 11), distance_m=6000.0)
    acts = session.exec(select(Activity)).all()

    buckets = _bucket_by_week_sun_start(acts, start, end)

    # 2026 has 53 Sunday-bucketed weeks (Sun Dec 28 2025 → Sun Dec 27 2026)
    assert len(buckets) == 53
    assert buckets[0]["date"] == "2025-12-28"
    assert buckets[0]["label"] == "Jan 1"
    assert buckets[0]["km"] == 8.0   # only Jan 2 run counts
    assert buckets[1]["date"] == "2026-01-04"
    assert buckets[1]["label"] == "Jan 4"
    assert buckets[2]["date"] == "2026-01-11"
    assert buckets[2]["km"] == 6.0
    # Last bucket starts Sun Dec 27 2026
    assert buckets[-1]["date"] == "2026-12-27"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tim/projects/dromos/backend && python3 -m pytest tests/test_builder.py::test_bucket_by_week_sun_start_2026 -v
```

Expected: `ImportError: cannot import name '_bucket_by_week_sun_start'`.

- [ ] **Step 3: Implement `_bucket_by_week_sun_start`**

Add to `backend/app/services/builder.py` immediately after `_bucket_by_day`:

```python
def _sunday_on_or_before(d: date) -> date:
    """Return the Sunday on or before d. Python: weekday() Mon=0..Sun=6."""
    days_since_sun = (d.weekday() + 1) % 7   # Sun=0, Mon=1, ... Sat=6
    return d - timedelta(days=days_since_sun)


def _bucket_by_week_sun_start(acts, start: date, end: date) -> list[dict]:
    """
    Sunday-start weekly buckets covering [start, end].

    The first bucket's date is the Sunday on or before `start`.
    The bucket's `label` is the first calendar date within [start, end] that
    falls in that week (e.g., "Jan 1" if the year starts mid-week).
    Only activities with date in [start, end] count toward the km totals.
    """
    first_sun = _sunday_on_or_before(start)
    buckets = []
    cur = first_sun
    while cur <= end:
        week_end = cur + timedelta(days=6)
        # Sum mileage for activities whose date is in [max(cur,start), min(week_end,end)]
        clamp_lo = max(cur, start)
        clamp_hi = min(week_end, end)
        total_m = 0.0
        for a in acts:
            d = a.started_at.date()
            if clamp_lo <= d <= clamp_hi:
                total_m += a.distance_m
        # Label: first in-range date in this week
        label_date = clamp_lo
        label = f"{label_date.strftime('%b')} {label_date.day}"
        buckets.append({
            "date": cur.isoformat(),
            "label": label,
            "km": round(total_m / 1000.0, 2),
        })
        cur += timedelta(days=7)
    return buckets
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/tim/projects/dromos/backend && python3 -m pytest tests/test_builder.py::test_bucket_by_week_sun_start_2026 -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/builder.py backend/tests/test_builder.py
git commit -m "feat(builder): add Sunday-start weekly bucketing for year view"
```

---

### Task 3: `_compute_period_data` orchestrator

**Files:**
- Modify: `backend/app/services/builder.py`
- Modify: `backend/tests/test_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_builder.py`:

```python
def test_compute_period_data_last_7_days_sum_matches_summary(session):
    """volume[period].total_km MUST equal summary[period].total_distance_km."""
    today = _date(2026, 5, 20)
    _make_act(session, _date(2026, 5, 16), distance_m=5000.0)
    _make_act(session, _date(2026, 5, 18), distance_m=8000.0)
    _make_act(session, _date(2026, 4, 30), distance_m=99000.0)  # OUT of 7-day window
    acts = session.exec(select(Activity)).all()

    summary, volume = _compute_period_data(acts, "last_7_days", today)

    assert summary["count"] == 2
    assert summary["total_distance_km"] == 13.0
    assert volume["total_km"] == 13.0
    assert sum(b["km"] for b in volume["buckets"]) == 13.0
    assert len(volume["buckets"]) == 7


def test_compute_period_data_month_uses_calendar_boundaries(session):
    today = _date(2026, 5, 20)
    _make_act(session, _date(2026, 5, 1), distance_m=4000.0)     # in
    _make_act(session, _date(2026, 5, 31), distance_m=10000.0)   # in (future, today=20th)
    _make_act(session, _date(2026, 4, 30), distance_m=99000.0)   # OUT
    _make_act(session, _date(2026, 6, 1), distance_m=99000.0)    # OUT
    acts = session.exec(select(Activity)).all()

    summary, volume = _compute_period_data(acts, "month", today)

    assert summary["count"] == 2
    assert summary["total_distance_km"] == 14.0
    assert volume["total_km"] == 14.0
    assert len(volume["buckets"]) == 31  # May has 31 days
    assert volume["buckets"][0]["km"] == 4.0
    assert volume["buckets"][30]["km"] == 10.0


def test_compute_period_data_year_53_weeks_2026(session):
    today = _date(2026, 5, 20)
    _make_act(session, _date(2026, 1, 2), distance_m=8000.0)
    _make_act(session, _date(2025, 12, 31), distance_m=99000.0)  # OUT (prior year)
    acts = session.exec(select(Activity)).all()

    summary, volume = _compute_period_data(acts, "year", today)

    assert summary["count"] == 1
    assert summary["total_distance_km"] == 8.0
    assert volume["total_km"] == 8.0
    assert len(volume["buckets"]) == 53
    assert volume["buckets"][0]["km"] == 8.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tim/projects/dromos/backend && python3 -m pytest tests/test_builder.py::test_compute_period_data_last_7_days_sum_matches_summary tests/test_builder.py::test_compute_period_data_month_uses_calendar_boundaries tests/test_builder.py::test_compute_period_data_year_53_weeks_2026 -v
```

Expected: `ImportError: cannot import name '_compute_period_data'`.

- [ ] **Step 3: Implement `_compute_period_data`**

Add to `backend/app/services/builder.py` immediately after `_bucket_by_week_sun_start`:

```python
def _weighted_avg_pace_s_per_km(acts) -> float | None:
    """Total duration / total distance (km), matching summary card math."""
    total_km = sum(a.distance_m for a in acts) / 1000.0
    total_s = sum(a.duration_s for a in acts)
    if total_km <= 0:
        return None
    return round(total_s / total_km, 1)


def _compute_period_data(acts, period: str, today: date) -> tuple[dict, dict]:
    """
    Compute summary and volume for one period.

    Returns (summary_dict, volume_dict). The invariant
    summary["total_distance_km"] == volume["total_km"] is enforced by construction.
    """
    if period == "last_7_days":
        start = today - timedelta(days=6)
        end = today
        buckets = None  # daily, weekday labels
        label_style = "weekday"
        weekly = False
    elif period == "month":
        start = today.replace(day=1)
        # First of next month, then back one day
        if start.month == 12:
            end = date(start.year, 12, 31)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        label_style = "day_of_month"
        weekly = False
    elif period == "year":
        start = date(today.year, 1, 1)
        end = date(today.year, 12, 31)
        weekly = True
    else:
        raise ValueError(f"unknown period: {period}")

    in_period = [a for a in acts if start <= a.started_at.date() <= end]
    total_km = round(sum(a.distance_m for a in in_period) / 1000.0, 2)

    summary = {
        "period": period,
        "count": len(in_period),
        "total_distance_km": total_km,
        "total_duration_s": sum(a.duration_s for a in in_period),
        "total_elevation_m": round(sum(a.elevation_gain_m or 0 for a in in_period), 1),
        "avg_pace_s_per_km": _weighted_avg_pace_s_per_km(in_period),
    }

    if weekly:
        buckets = _bucket_by_week_sun_start(in_period, start, end)
    else:
        buckets = _bucket_by_day(in_period, start, end, label_style)

    volume = {"buckets": buckets, "total_km": total_km}
    return summary, volume
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tim/projects/dromos/backend && python3 -m pytest tests/test_builder.py -v -k "period_data or bucket_by"
```

Expected: 6 passed (3 bucket + 3 period_data).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/builder.py backend/tests/test_builder.py
git commit -m "feat(builder): add _compute_period_data orchestrator"
```

---

## Chunk 2: Wire `_rebuild_dashboard` to new shape

### Task 4: Switch `_rebuild_dashboard` to write `summary` + `volume`

**Files:**
- Modify: `backend/app/services/builder.py:293-301`
- Modify: `backend/tests/test_builder.py`

- [ ] **Step 1: Write the failing test for the new dashboard.json shape**

Append to `backend/tests/test_builder.py`:

```python
def test_rebuild_globals_writes_volume_field(session, tmp_path, monkeypatch):
    """dashboard.json must contain summary{} and volume{} for all three periods."""
    # Freeze "today" so calendar-bound logic is deterministic.
    # Patch the symbol that builder.py uses internally.
    fake_today = _date(2026, 5, 20)

    import app.services.builder as builder_mod
    monkeypatch.setattr(builder_mod, "_today_fn", lambda: fake_today)

    _make_act(session, _date(2026, 5, 16), distance_m=5000.0)
    _make_act(session, _date(2026, 5, 18), distance_m=8000.0)

    rebuild_globals(session, static_dir=tmp_path)

    data = json.loads((tmp_path / "dashboard.json").read_text())
    assert set(data["summary"].keys()) == {"last_7_days", "month", "year"}
    assert set(data["volume"].keys()) == {"last_7_days", "month", "year"}

    last_7 = data["volume"]["last_7_days"]
    assert last_7["total_km"] == 13.0
    assert sum(b["km"] for b in last_7["buckets"]) == 13.0
    # And the cross-field invariant holds
    assert data["summary"]["last_7_days"]["total_distance_km"] == last_7["total_km"]

    month = data["volume"]["month"]
    assert len(month["buckets"]) == 31
    # Future days (May 21..31) should be 0
    assert month["buckets"][20]["date"] == "2026-05-21"
    assert month["buckets"][20]["km"] == 0.0

    year = data["volume"]["year"]
    assert len(year["buckets"]) == 53
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tim/projects/dromos/backend && python3 -m pytest tests/test_builder.py::test_rebuild_globals_writes_volume_field -v
```

Expected: KeyError on `data["volume"]` or similar — the current `_rebuild_dashboard` only writes `summary` with old period keys.

- [ ] **Step 3: Add `_today_fn` indirection + rewrite `_rebuild_dashboard`**

In `backend/app/services/builder.py`, **above** the existing `_rebuild_dashboard`:

```python
def _today_fn() -> date:
    """Indirection so tests can freeze 'today' via monkeypatch."""
    return date.today()
```

Then **replace** the existing `_rebuild_dashboard` (lines 293-301) with:

```python
def _rebuild_dashboard(session: Session, static_dir: Path) -> None:
    from app.routers.stats import get_training_load, get_vdot, get_personal_bests
    from app.models import Activity

    acts = session.exec(select(Activity)).all()
    today = _today_fn()

    summary = {}
    volume = {}
    for p in ("last_7_days", "month", "year"):
        s, v = _compute_period_data(acts, p, today)
        summary[p] = s
        volume[p] = v

    _write_json(static_dir / "dashboard.json", {
        "summary": summary,
        "volume": volume,
        "training_load": get_training_load(days=365, session=session),
        "vdot": get_vdot(session=session),
        "personal_bests": get_personal_bests(session=session),
    })
```

Note: we no longer call `get_summary` from the router — its server-side cache and rolling-window logic are bypassed entirely. The endpoint still exists but is now redundant.

- [ ] **Step 4: Run all builder tests**

```bash
cd /home/tim/projects/dromos/backend && python3 -m pytest tests/test_builder.py -v
```

Expected: all green, including the new dashboard shape test.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/builder.py backend/tests/test_builder.py
git commit -m "feat(builder): rewrite _rebuild_dashboard to emit volume buckets"
```

---

## Chunk 3: Hygiene — update unused stats API regex

### Task 5: Tighten `get_summary` regex

**Files:**
- Modify: `backend/app/routers/stats.py:92-114`

The frontend doesn't use this endpoint anymore (everything reads from `dashboard.json`), but the regex should match the new period vocabulary for consistency. We'll also remove the now-dead rolling-window branches.

- [ ] **Step 1: Update `get_summary` signature and body**

In `backend/app/routers/stats.py`, replace lines 92-136 with:

```python
@router.get("/summary")
def get_summary(
    period: str = Query("last_7_days", pattern="^(last_7_days|month|year)$"),
    session: Session = Depends(get_session),
):
    """
    Aggregate run counts, distance, duration, elevation for a calendar-bound period.

    Note: the dashboard reads /static/dashboard.json directly (built by
    app.services.builder._rebuild_dashboard). This endpoint exists for
    API consumers and re-derives from the static file for consistency.
    """
    from app.services.builder import STATIC_DIR
    import json as _json
    path = STATIC_DIR / "dashboard.json"
    if not path.exists():
        return {"period": period, "count": 0, "total_distance_km": 0.0,
                "total_duration_s": 0, "total_elevation_m": 0.0,
                "avg_pace_s_per_km": None}
    data = _json.loads(path.read_text())
    return data["summary"].get(period, {})
```

- [ ] **Step 2: Remove the now-unused `_summary_cache` and `warm_cache` entries**

In `backend/app/routers/stats.py`:
- Remove `_summary_cache: dict = {}` and `_SUMMARY_TTL = 300` near the top.
- Remove the `_summary_cache.clear()` line from `_invalidate_stats_cache`.
- In `warm_cache`, remove the two `get_summary(period=...)` calls (they're not needed — the dashboard.json file is the cache now).

- [ ] **Step 3: Run all backend tests to ensure no regression**

```bash
cd /home/tim/projects/dromos/backend && python3 -m pytest -v
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/stats.py
git commit -m "refactor(stats): drop rolling-window summary cache; serve from static file"
```

---

## Chunk 4: Frontend — API client + Dashboard wiring

### Task 6: Update `api/client.ts`

**Files:**
- Modify: `frontend/src/api/client.ts:24` (and add new export)

- [ ] **Step 1: Update `getStatsSummary` + add `getVolumeBuckets`**

Replace lines 23-25 of `frontend/src/api/client.ts` with:

```ts
export type Period = "last_7_days" | "month" | "year";

// Stats: all come from dashboard.json; each function extracts its slice.
export const getStatsSummary = (period: Period = "last_7_days") =>
  _fetchJson("/static/dashboard.json").then((d) => d.summary[period]);

export const getVolumeBuckets = (period: Period) =>
  _fetchJson("/static/dashboard.json").then((d) => d.volume[period]);
```

- [ ] **Step 2: Verify the file compiles (TypeScript)**

```bash
cd /home/tim/projects/dromos/frontend && npx tsc --noEmit -p tsconfig.json
```

Expected: no errors related to `client.ts`. There may be errors in `Dashboard.tsx` / `App.tsx` if they pass old period strings — those are addressed in Tasks 7 and 8.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(client): add getVolumeBuckets, switch period type to calendar-bound"
```

---

### Task 7: Replace `Last7Days` with `VolumeChart` in `Dashboard.tsx`

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx:287–337` (delete `Last7Days`)
- Modify: `frontend/src/pages/Dashboard.tsx:341–345` (PERIODS constant)
- Modify: `frontend/src/pages/Dashboard.tsx:370–385` (button row labels)
- Modify: `frontend/src/pages/Dashboard.tsx:399–400` (component swap)

- [ ] **Step 1: Update imports at top of `Dashboard.tsx`**

Add `getVolumeBuckets` (and remove unused `formatDateMonthDay` if it's only used by `Last7Days`):

```ts
import { getStatsSummary, getActivities, getPersonalBests, getGoals, getActivityFull, getDataPoints, getVolumeBuckets } from "../api/client";
import type { Period } from "../api/client";
```

- [ ] **Step 2: Replace PERIODS constant (line 341)**

```ts
const PERIODS = ["last_7_days", "month", "year"] as const;

const PERIOD_LABELS: Record<Period, string> = {
  last_7_days: "Last 7 days",
  month: "Month",
  year: "Year",
};
```

- [ ] **Step 3: Update the button row (lines ~370–385)**

Replace the `{PERIODS.map((p) => …)}` block button label expression `p.charAt(0).toUpperCase() + p.slice(1)` with `PERIOD_LABELS[p]`.

- [ ] **Step 4: Delete the old `Last7Days` component (lines 287–337)**

The whole `function Last7Days(...) { ... }` block plus the `DAY_LABELS` constant (line 289) are removed.

- [ ] **Step 5: Add `VolumeChart` component**

Insert in place of the deleted `Last7Days` (around line 287):

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

  const rows = data.buckets.map((b: { label: string; km: number }) => ({
    label: b.label,
    dist: toDisplay(b.km),
  }));
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

- [ ] **Step 6: Replace the chart usage**

Change line ~400 from `<Last7Days acts={allActs} />` to `<VolumeChart period={period} />`.

The Dashboard's `useState<Period>("week")` default needs updating to `useState<Period>("last_7_days")`.

- [ ] **Step 7: TypeScript check**

```bash
cd /home/tim/projects/dromos/frontend && npx tsc --noEmit -p tsconfig.json
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat(dashboard): replace Last7Days with period-aware VolumeChart"
```

---

### Task 8: Update prefetch keys in `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx:32–33`

- [ ] **Step 1: Update prefetch lines**

Replace:

```ts
queryClient.prefetchQuery({ queryKey: ["stats-summary", "week"],  queryFn: () => getStatsSummary("week"),    staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["stats-summary", "month"], queryFn: () => getStatsSummary("month"),   staleTime: Infinity });
```

With:

```ts
queryClient.prefetchQuery({ queryKey: ["stats-summary", "last_7_days"], queryFn: () => getStatsSummary("last_7_days"), staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["stats-summary", "month"],       queryFn: () => getStatsSummary("month"),       staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["stats-summary", "year"],        queryFn: () => getStatsSummary("year"),        staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["volume", "last_7_days"],        queryFn: () => getVolumeBuckets("last_7_days"), staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["volume", "month"],              queryFn: () => getVolumeBuckets("month"),       staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["volume", "year"],               queryFn: () => getVolumeBuckets("year"),        staleTime: Infinity });
```

(All six prefetches share one HTTP request to `dashboard.json` thanks to React Query's de-duping.)

Add `getVolumeBuckets` to the import on line 6.

- [ ] **Step 2: TypeScript check**

```bash
cd /home/tim/projects/dromos/frontend && npx tsc --noEmit -p tsconfig.json
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(app): prefetch volume buckets for all three periods"
```

---

## Chunk 5: Local verification

### Task 9: Restart local backend and verify `dashboard.json`

- [ ] **Step 1: Find and kill the running uvicorn process**

```bash
pgrep -f "uvicorn app.main" | xargs -r kill
```

(Do NOT use `pkill -f` — per debugging note in the repo memory, it has matched its own bash command in the past.)

- [ ] **Step 2: Restart uvicorn detached from this session**

```bash
cd /home/tim/projects/dromos/backend && setsid nohup ../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/dromos-backend.log 2>&1 < /dev/null &
disown
```

- [ ] **Step 3: Wait ~3 seconds then verify the rebuild fired and the new field is present**

```bash
sleep 3 && python3 -c "import json; d=json.load(open('/home/tim/projects/dromos/data-dev/static/dashboard.json')); print('summary keys:', list(d.get('summary',{}).keys())); print('volume keys:', list(d.get('volume',{}).keys())); print('month buckets:', len(d['volume']['month']['buckets'])); print('year buckets:', len(d['volume']['year']['buckets']))"
```

Expected output:
```
summary keys: ['last_7_days', 'month', 'year']
volume keys: ['last_7_days', 'month', 'year']
month buckets: 31    (or 30/28 depending on current month)
year buckets: 52     (or 53)
```

(Adjust the `data-dev` path if your local DATA_DIR is elsewhere.)

- [ ] **Step 4: Verify the StatCards-vs-chart invariant in the static file**

```bash
python3 -c "import json; d=json.load(open('/home/tim/projects/dromos/data-dev/static/dashboard.json'));
for p in ('last_7_days','month','year'):
    s=d['summary'][p]['total_distance_km']; v=d['volume'][p]['total_km']
    assert s==v, f'{p}: summary={s} volume={v}'; print(f'{p} OK: {s} km')"
```

Expected: three lines, no `AssertionError`.

---

### Task 10: Browser verification

- [ ] **Step 1: Ensure vite dev server is running**

```bash
pgrep -f "vite" >/dev/null || (cd /home/tim/projects/dromos/frontend && setsid nohup npm run dev -- --host > /tmp/dromos-vite.log 2>&1 < /dev/null & disown)
```

- [ ] **Step 2: Manual smoke test (open browser)**

Open `http://192.168.0.233:5173/` and verify:

- The toggle row reads **Last 7 days · Month · Year** (no "Week", no "All").
- "Last 7 days" is selected by default; the chart shows 7 daily bars labeled Sun..Sat.
- The chart total in the top-right of the chart card equals the "Distance" StatCard above it.
- Clicking **Month** shows N daily bars (N = days-in-current-month) labeled `1..31`. Future days are empty bars. Chart total still equals StatCard Distance.
- Clicking **Year** shows ~52 weekly bars; first label is `Jan 1` (or near it); Recharts thins x-axis labels automatically.
- Hover tooltip shows `<distance> km` (or `mi` if you toggle units).
- Imperial unit toggle continues to flip both StatCards and chart values.

- [ ] **Step 3: Note any unexpected behavior in `/tmp/dromos-verify.log`** (no actual command needed — just record findings before committing)

---

## Chunk 6: Ship

### Task 11: Commit & push to GitHub

- [ ] **Step 1: Confirm working tree clean except for any deliberate WIP**

```bash
cd /home/tim/projects/dromos && git status
```

- [ ] **Step 2: Push to origin/master**

```bash
git push origin master
```

---

### Task 12: Docker build & deploy to coruscant

- [ ] **Step 1: Build the docker image locally**

```bash
cd /home/tim/projects/dromos && docker build -f Dockerfile -t ricetim/dromos:latest .
```

(If the project has a separate frontend+backend Dockerfile flow, follow whichever is captured in CLAUDE.md / recent commit messages — the repo memory notes the project ships as a single-image deployment.)

- [ ] **Step 2: Push to DockerHub**

```bash
docker push ricetim/dromos:latest
```

- [ ] **Step 3: Deploy to coruscant**

The user runs this on their server:

```bash
ssh coruscant 'cd ~/.docker_config/dromos && docker compose pull && docker compose down && docker compose up -d'
```

Per project memory: **never use `docker compose restart`** — image digests get pinned and the new image isn't picked up. Always `down && up`.

- [ ] **Step 4: Smoke-test the production URL**

Open `http://dromos.timothyrice.org/` and run through the same checklist as Task 10 Step 2.

---

## Rollback

If the new dashboard.json shape causes issues in production, the safest rollback is:

```bash
# On coruscant
docker tag ricetim/dromos:prev ricetim/dromos:latest
docker compose down && docker compose up -d
```

(Assumes a `prev` tag was pushed before the new image. If not, `git revert` the commits and rebuild.)

## Out of scope (per spec)

- No backwards-compat shim for `week` / `all` period keys.
- No precomputed imperial units (frontend converts).
- No "All-time" widget.
