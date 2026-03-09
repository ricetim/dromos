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

// Stats: all come from dashboard.json; each function extracts its slice.
export const getStatsSummary = (period = "week") =>
  _fetchJson("/static/dashboard.json").then((d) => d.summary[period]);

export const getTrainingLoad = (days = 90) =>
  _fetchJson("/static/dashboard.json").then(
    (d: { training_load: { date: string }[] }) => {
      const cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - days);
      return d.training_load.filter((row) => new Date(row.date) >= cutoff);
    }
  );

export const getVdot = () =>
  _fetchJson("/static/dashboard.json").then((d) => d.vdot);

export const getPersonalBests = () =>
  _fetchJson("/static/dashboard.json").then((d) => d.personal_bests);

export const getGoals = () => _fetchJson("/static/goals.json");

export const getShoes = () => _fetchJson("/static/shoes.json");

export const getMetrics = () => _fetchJson("/static/metrics.json");

export const getPlans = () => _fetchJson("/static/plans.json");

export const getPlan = (id: number) =>
  _fetchJson(`/static/plan-${id}.json`).then((d) => d.plan);

export const getPlanWorkouts = (id: number) =>
  _fetchJson(`/static/plan-${id}.json`).then((d) => d.workouts);

// ── write operations (still go through FastAPI) ───────────────────────────

export const uploadFit = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return api.post("/activities/upload", fd).then((r) => r.data);
};

export const updateActivity = (id: number, data: object) =>
  api.patch(`/activities/${id}`, data).then((r) => r.data);

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

export const createPlan = (data: object) =>
  api.post("/plans", data).then((r) => r.data);

export const deletePlan = (id: number) => api.delete(`/plans/${id}`);

export const updatePlanWorkout = (
  planId: number,
  workoutId: number,
  data: object
) =>
  api
    .patch(`/plans/${planId}/workouts/${workoutId}`, data)
    .then((r) => r.data);

export const getProfile = () => api.get("/profile").then((r) => r.data);

export const getSyncStatus = () =>
  api.get("/sync/status").then((r) => r.data);

export const triggerSync = () =>
  api.post("/sync/trigger").then((r) => r.data);

export const getActivityAnalytics = (id: number) =>
  api.get(`/stats/activities/${id}/analytics`).then((r) => r.data);

export const getPhotos = (id: number) =>
  api.get(`/activities/${id}/photos`).then((r) => r.data);
