import axios from "axios";

const api = axios.create({ baseURL: "/api" });

// ── helpers ────────────────────────────────────────────────────────────────

const _fetchJson = (url: string) =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error(`Static fetch failed: ${r.status} ${url}`);
    return r.json();
  });

// ── static reads (served by nginx from /data/static/) ─────────────────────

export const getActivities = () => _fetchJson("/static/activities.json");

export const getActivityFull = (id: number) =>
  _fetchJson(`/static/activity-${id}.json`);

export const getDataPoints = (id: number) =>
  _fetchJson(`/static/datapoints-${id}.json`);

export type Period = "last_7_days" | "month" | "year";

// Stats: all come from dashboard.json; each function extracts its slice.
//
// Several React Query keys (stats-summary ×3, volume ×3, vdot, personal-bests)
// read this one file, and React Query only dedupes within a key — so app boot
// fired eight parallel fetches of the same payload. Share the *in-flight*
// promise so concurrent callers collapse into one request, then drop it once
// settled: a later refetch (e.g. after invalidateQueries) still hits the
// network and sees the rebuilt file.
let _dashInFlight: ReturnType<typeof _fetchJson> | null = null;

const _dashboard = () => {
  if (!_dashInFlight) {
    const p = _fetchJson("/static/dashboard.json");
    _dashInFlight = p;
    // Settle handler that swallows nothing: `p` keeps its own rejection for
    // callers, this chain just clears the slot without an unhandled rejection.
    p.then(
      () => {},
      () => {},
    ).then(() => {
      if (_dashInFlight === p) _dashInFlight = null;
    });
  }
  return _dashInFlight;
};

export const getStatsSummary = (period: Period = "last_7_days") =>
  _dashboard().then((d) => d.summary[period]);

export const getVolumeBuckets = (period: Period) =>
  _dashboard().then((d) => d.volume[period]);

export const getVdot = () => _dashboard().then((d) => d.vdot);

export const getPersonalBests = () => _dashboard().then((d) => d.personal_bests);

export const getGoals = () => _fetchJson("/static/goals.json");

export const getShoes = () => _fetchJson("/static/shoes.json");
export const getShoesTimeline = () => _fetchJson("/static/shoes_timeline.json");

export const getMetrics = () => _fetchJson("/static/metrics.json");

// ── write operations (still go through FastAPI) ───────────────────────────

export const uploadFit = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return api.post("/activities/upload", fd).then((r) => r.data);
};

export const updateActivity = (id: number, data: object) =>
  api.patch(`/activities/${id}`, data).then((r) => r.data);

export const refreshActivityFromCoros = (id: number) =>
  api.post(`/activities/${id}/refresh-coros`).then((r) => r.data);

export const deleteActivity = (id: number) => api.delete(`/activities/${id}`);

export const createGoal = (data: object) =>
  api.post("/goals", data).then((r) => r.data);

export const updateGoal = (id: number, data: object) =>
  api.put(`/goals/${id}`, data).then((r) => r.data);

export const deleteGoal = (id: number) => api.delete(`/goals/${id}`);

export const createShoe = (data: object) =>
  api.post("/shoes", data).then((r) => r.data);

export const updateShoe = (id: number, data: object) =>
  api.patch(`/shoes/${id}`, data).then((r) => r.data);

export const updateActivityShoe = (activityId: number, shoeId: number | null) =>
  api.patch(`/activities/${activityId}/shoe`, { shoe_id: shoeId }).then((r) => r.data);

export const setDefaultShoe = (shoeId: number | null) =>
  api.patch("/profile", { default_shoe_id: shoeId }).then((r) => r.data);

export const getPhotos = (id: number) =>
  api.get(`/activities/${id}/photos`).then((r) => r.data);
