import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from "recharts";
import { getStatsSummary, getActivities, getPersonalBests, getGoals, getActivityFull, getDataPoints } from "../api/client";
import type { Activity } from "../types";
import { useUnits } from "../contexts/UnitsContext";
import { formatDateMonthDay, formatDateLong } from "../utils/dates";
import RouteThumbnail from "../components/RouteThumbnail";
import RpeBadge from "../components/RpeBadge";

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

// ── stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1 shadow-sm">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-bold text-gray-800">{value}</div>
      {sub && <div className="text-xs text-gray-400">{sub}</div>}
    </div>
  );
}

// ── personal bests ────────────────────────────────────────────────────────────

const PB_DISTANCES = [
  "400m", "800m", "1k", "1 mile", "2 mile", "3k", "5k", "8k",
  "10k", "15k", "10 mile", "20k", "half", "25k", "30k", "marathon",
] as const;

type PBEntry = { rank: number; time_s: number; activity_id: number; start_elapsed_s: number; end_elapsed_s: number };
type PBData = Record<string, PBEntry[] | null>;

function PersonalBests() {
  const { data, isLoading } = useQuery<PBData>({
    queryKey: ["personal-bests"],
    queryFn: getPersonalBests,
    staleTime: Infinity,  // static file — only changes after a write
  });

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">Personal Bests</h2>
      {isLoading ? (
        <div className="text-sm text-gray-400">Loading…</div>
      ) : (
        <div className="divide-y divide-gray-50">
          {PB_DISTANCES.map((label) => {
            const best = data?.[label]?.[0] ?? null;
            return (
              <div key={label} className="flex items-center justify-between py-1.5">
                <span className="text-sm text-gray-600 w-20">{label}</span>
                {best != null ? (
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-900 font-mono">
                      {fmtTime(best.time_s)}
                    </span>
                    <Link
                      to={`/activities/${best.activity_id}?seg_start=${best.start_elapsed_s}&seg_end=${best.end_elapsed_s}`}
                      className="text-blue-500 hover:text-blue-700 text-sm leading-none"
                      title="View segment in activity"
                    >
                      →
                    </Link>
                  </div>
                ) : (
                  <span className="text-sm text-gray-300">—</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── goals widget ─────────────────────────────────────────────────────────────

function GoalsWidget() {
  const { fmtDist, system } = useUnits();
  const { data: goals = [] } = useQuery<{ goal: { id: number; type: string; target_value: number; period_start: string; period_end: string }; progress_km: number }[]>({
    queryKey: ["goals"],
    queryFn: getGoals,
    staleTime: Infinity,  // static file — only changes after a write
  });

  if (goals.length === 0) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-700">Goals</h2>
        <Link to="/goals" className="text-xs text-blue-600 hover:underline">Manage →</Link>
      </div>
      <div className="space-y-3">
        {goals.map(({ goal, progress_km }) => {
          const target = system === "imperial" ? goal.target_value * 0.621371 : goal.target_value;
          const progress = system === "imperial" ? progress_km * 0.621371 : progress_km;
          const pct = Math.min(100, Math.round((progress / target) * 100));
          const label = goal.type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

          const now = Date.now();
          const start = new Date(goal.period_start).getTime();
          const end = new Date(goal.period_end).getTime();
          const totalDays = (end - start) || 1;
          const elapsed = Math.max(0, Math.min(now - start, totalDays));
          const expectedPct = elapsed / totalDays;
          const actualPct = progress_km / goal.target_value;
          const done = now >= end;
          const onTrack = actualPct >= expectedPct;

          const trackLabel = done
            ? pct >= 100 ? "Achieved!" : "Not reached"
            : onTrack ? "On track" : "Behind pace";
          const trackColor = done
            ? pct >= 100 ? "text-green-600" : "text-red-500"
            : onTrack ? "text-green-600" : "text-orange-500";

          // Projection: extrapolate current pace through end of period
          let projText: string | null = null;
          if (!done && elapsed > 0 && actualPct > 0) {
            const projKm = progress_km / (elapsed / totalDays);
            projText = `Projected: ${fmtDist(projKm * 1000)}`;
          }

          const isExpiredMiss = done && pct < 100;
          return (
            <div key={goal.id} className={isExpiredMiss ? "opacity-50" : ""}>
              <div className="flex justify-between text-xs text-gray-600 mb-1">
                <span className="flex items-center gap-1.5">
                  {label}
                  {isExpiredMiss && (
                    <span className="text-[10px] bg-gray-200 text-gray-500 px-1.5 py-0.5 rounded-full">Expired</span>
                  )}
                </span>
                <span className="font-medium">
                  {fmtDist(progress_km * 1000)} / {fmtDist(goal.target_value * 1000)}
                  <span className="ml-1 text-gray-400">({pct}%)</span>
                </span>
              </div>
              <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${pct >= 100 ? "bg-green-500" : isExpiredMiss ? "bg-gray-400" : "bg-blue-500"}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="flex items-center justify-between mt-0.5">
                <div className={`text-[10px] ${trackColor}`}>{trackLabel}</div>
                {projText && <div className="text-[10px] text-gray-400 italic">{projText}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── recent activity row ───────────────────────────────────────────────────────

function formatWorkoutName(sportType: string, plannedWorkoutType?: string | null, name?: string | null): string {
  if (name) return name;
  if (plannedWorkoutType) return plannedWorkoutType;
  return sportType.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function ActivityRow({ act }: { act: Activity }) {
  const { fmtDist, fmtPace } = useUnits();
  const qc = useQueryClient();
  return (
    <Link
      to={`/activities/${act.id}`}
      className="flex items-center gap-3 p-3 rounded-xl border border-gray-200 hover:border-blue-400 hover:shadow-sm transition-all"
      onMouseEnter={() => {
        qc.prefetchQuery({ queryKey: ["activity-full", act.id], queryFn: () => getActivityFull(act.id), staleTime: Infinity });
        qc.prefetchQuery({ queryKey: ["datapoints", act.id], queryFn: () => getDataPoints(act.id), staleTime: Infinity });
      }}
    >
      <RouteThumbnail track={act.track} width={96} height={72} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-xs text-gray-400">
            {formatDateMonthDay(act.started_at)}
          </span>
          {act.rpe != null && act.rpe > 0 && <RpeBadge rpe={act.rpe} />}
        </div>
        <div className="text-sm font-semibold text-gray-900 mb-0.5">
          {formatWorkoutName(act.sport_type, act.planned_workout_type, act.name)}
        </div>
        {act.notes && (
          <p className="text-xs text-gray-400 truncate">
            {act.notes.length > 80 ? act.notes.slice(0, 80) + "…" : act.notes}
          </p>
        )}
      </div>
      <div className="flex gap-3 text-sm text-right flex-shrink-0">
        <div>
          <div className="font-semibold text-gray-900">{fmtDist(act.distance_m)}</div>
          <div className="text-xs text-gray-400">dist</div>
        </div>
        <div>
          <div className="font-semibold text-gray-900">{fmtTime(act.duration_s)}</div>
          <div className="text-xs text-gray-400">time</div>
        </div>
        <div>
          <div className="font-semibold text-gray-900">{fmtPace(act.avg_pace_s_per_km)}</div>
          <div className="text-xs text-gray-400">pace</div>
        </div>
      </div>
    </Link>
  );
}

// ── featured (most recent) activity ──────────────────────────────────────────

function FeaturedActivity({ act }: { act: Activity }) {
  const { fmtDist, fmtPace } = useUnits();
  return (
    <Link
      to={`/activities/${act.id}`}
      className="block bg-white rounded-xl border border-gray-200 hover:border-blue-400 shadow-sm hover:shadow-md transition-all overflow-hidden"
    >
      <div className="flex flex-col sm:flex-row">
        {(act.track ?? []).length > 0 && (
          <div className="sm:w-56 sm:flex-shrink-0 bg-gray-50 flex items-center justify-center p-2">
            <RouteThumbnail track={act.track} width={200} height={140} />
          </div>
        )}
        <div className="flex-1 p-4">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-gray-400">
              {formatDateLong(act.started_at)}
            </span>
            {act.rpe != null && act.rpe > 0 && <RpeBadge rpe={act.rpe} />}
          </div>
          <div className="text-xl font-bold text-gray-900 mb-2">
            {act.name || act.sport_type.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ")}
          </div>
          <div className="flex flex-wrap gap-6">
            <div>
              <div className="text-2xl font-bold text-blue-600">{fmtDist(act.distance_m)}</div>
              <div className="text-xs text-gray-400">distance</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-gray-800">{fmtTime(act.duration_s)}</div>
              <div className="text-xs text-gray-400">time</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-gray-800">{fmtPace(act.avg_pace_s_per_km)}</div>
              <div className="text-xs text-gray-400">avg pace</div>
            </div>
            {act.avg_hr && (
              <div>
                <div className="text-2xl font-bold text-red-500">{act.avg_hr}</div>
                <div className="text-xs text-gray-400">bpm avg</div>
              </div>
            )}
          </div>
          {act.notes && (
            <p className="text-sm text-gray-500 mt-2 line-clamp-2">{act.notes}</p>
          )}
        </div>
      </div>
    </Link>
  );
}

// ── last 7 days volume ────────────────────────────────────────────────────────

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function Last7Days({ acts }: { acts: Activity[] }) {
  const { system } = useUnits();
  const distUnit = system === "imperial" ? "mi" : "km";

  const { data, totalDist } = useMemo(() => {
    const now = new Date();
    const days = Array.from({ length: 7 }, (_, i) => {
      const d = new Date(now);
      d.setDate(d.getDate() - (6 - i));
      return { key: d.toISOString().slice(0, 10), label: DAY_LABELS[d.getDay()], dist: 0 };
    });

    for (const act of acts) {
      const day = days.find((d) => d.key === act.started_at.slice(0, 10));
      if (!day) continue;
      day.dist += act.distance_m;
    }

    const toDisplay = (m: number) => system === "imperial" ? +(m / 1609.34).toFixed(1) : +(m / 1000).toFixed(1);
    const rows = days.map((d) => ({ label: d.label, dist: toDisplay(d.dist) }));
    const totalDist = toDisplay(days.reduce((s, d) => s + d.dist, 0));
    return { data: rows, totalDist };
  }, [acts, system]);

  if (!data.some((d) => d.dist > 0)) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-700">Last 7 Days</h2>
        <span className="text-sm font-bold text-gray-800">{totalDist} {distUnit}</span>
      </div>
      <ResponsiveContainer width="100%" height={110}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }} barCategoryGap="25%">
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 10 }} width={36} unit={` ${distUnit}`} />
          <Tooltip
            contentStyle={{ fontSize: 12 }}
            formatter={(v: number) => [`${v} ${distUnit}`, "Distance"]}
          />
          <Bar dataKey="dist" fill="#3b82f6" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── main Dashboard ────────────────────────────────────────────────────────────

const PERIODS = ["week", "month", "year", "all"] as const;
type Period = (typeof PERIODS)[number];

export default function Dashboard() {
  const [period, setPeriod] = useState<Period>("week");
  const { fmtDist, fmtPace, fmtElev } = useUnits();

  const { data: summary } = useQuery({
    queryKey: ["stats-summary", period],
    queryFn: () => getStatsSummary(period),
    staleTime: Infinity,  // static file — only changes after a write
  });

  const { data: activities } = useQuery({
    queryKey: ["activities"],
    queryFn: getActivities,
    staleTime: Infinity,  // static file — only changes after a write
  });

  const allActs: Activity[] = activities ?? [];
  const latestAct = allActs[0] ?? null;
  const recentActs: Activity[] = allActs.slice(1, 8);

  return (
    <div className="p-4 max-w-5xl mx-auto space-y-6">

      {/* Goals — always at top */}
      <GoalsWidget />

      {/* Period toggle */}
      <div className="flex items-center gap-2">
        {PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`px-3 py-1 text-sm rounded-full border transition-colors ${
              period === p
                ? "bg-blue-600 text-white border-blue-600"
                : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
            }`}
          >
            {p.charAt(0).toUpperCase() + p.slice(1)}
          </button>
        ))}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Runs"     value={summary?.count ?? "–"} />
        <StatCard label="Distance" value={summary ? fmtDist(summary.total_distance_km * 1000) : "–"} />
        <StatCard label="Time"     value={summary ? fmtTime(summary.total_duration_s) : "–"} />
        <StatCard
          label="Avg pace"
          value={fmtPace(summary?.avg_pace_s_per_km ?? null)}
          sub={summary ? `${fmtElev(summary.total_elevation_m)} gain` : "–"}
        />
      </div>

      {/* Last 7 days volume + TRIMP */}
      <Last7Days acts={allActs} />

      {/* Most recent activity — large card */}
      {latestAct && (
        <div className="border-l-4 border-blue-500 pl-3">
          <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-widest mb-2">Most Recent Run</h2>
          <FeaturedActivity act={latestAct} />
        </div>
      )}

      {/* Personal bests */}
      <PersonalBests />

      {/* Recent activities */}
      {recentActs.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-gray-700">Recent Activities</h2>
            <Link to="/activities" className="text-xs text-blue-600 hover:underline">View all →</Link>
          </div>
          <div className="space-y-2">
            {recentActs.map((act) => (
              <ActivityRow key={act.id} act={act} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
