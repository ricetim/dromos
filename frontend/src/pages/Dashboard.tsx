import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from "recharts";
import { getStatsSummary, getActivities, getPersonalBests, getGoals, getActivityFull, getDataPoints, getProfile } from "../api/client";
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

// ── rolling 7-day volume + TRIMP chart ───────────────────────────────────────

function RollingVolume({ acts }: { acts: Activity[] }) {
  const { system } = useUnits();
  const distUnit = system === "imperial" ? "mi" : "km";

  const { data: profile } = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
    staleTime: Infinity,
  });
  const hrMax = profile?.hr_max ?? 185;
  const hrRest = profile?.hr_rest ?? 50;

  const data = useMemo(() => {
    // Aggregate distance (m) and TRIMP per calendar day
    const dayMap: Record<string, { dist_m: number; trimp: number }> = {};
    for (const act of acts) {
      const day = act.started_at.slice(0, 10);
      if (!dayMap[day]) dayMap[day] = { dist_m: 0, trimp: 0 };
      dayMap[day].dist_m += act.distance_m;
      if (act.avg_hr && act.duration_s) {
        const hrRatio = Math.max(0, (act.avg_hr - hrRest) / (hrMax - hrRest));
        if (hrRatio > 0)
          dayMap[day].trimp += (act.duration_s / 60) * hrRatio * 0.64 * Math.exp(1.92 * hrRatio);
      }
    }

    // Rolling 7-day sums for each of the last 90 days
    const result = [];
    const now = new Date();
    for (let i = 89; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const label = `${d.getMonth() + 1}/${d.getDate()}`;
      let dist7 = 0, trimp7 = 0;
      for (let j = 6; j >= 0; j--) {
        const prev = new Date(d);
        prev.setDate(d.getDate() - j);
        const key = prev.toISOString().slice(0, 10);
        if (dayMap[key]) { dist7 += dayMap[key].dist_m; trimp7 += dayMap[key].trimp; }
      }
      const distDisplay = system === "imperial" ? dist7 / 1609.34 : dist7 / 1000;
      result.push({ date: label, dist7: +distDisplay.toFixed(1), trimp7: +trimp7.toFixed(0) });
    }
    return result;
  }, [acts, system, hrMax, hrRest]);

  if (!data.some((d) => d.dist7 > 0)) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">
        Rolling 7-Day Load{" "}
        <span className="font-normal text-gray-400 text-xs">(last 90 days)</span>
      </h2>
      <ResponsiveContainer width="100%" height={130}>
        <ComposedChart data={data} margin={{ top: 4, right: 44, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
          <XAxis dataKey="date" tick={{ fontSize: 10 }} interval={13} />
          <YAxis yAxisId="dist" tick={{ fontSize: 10 }} width={38} unit={` ${distUnit}`} />
          <YAxis yAxisId="trimp" orientation="right" tick={{ fontSize: 10 }} width={38} unit=" AU" />
          <Tooltip
            contentStyle={{ fontSize: 12 }}
            formatter={(v: number, name: string) =>
              name === "dist7"
                ? [`${v.toFixed(1)} ${distUnit}`, "7-day dist"]
                : [`${Math.round(v)} AU`, "7-day TRIMP"]
            }
          />
          <Area yAxisId="dist" type="monotone" dataKey="dist7" fill="#dbeafe" stroke="#3b82f6" strokeWidth={2} dot={false} />
          <Line yAxisId="trimp" type="monotone" dataKey="trimp7" stroke="#f97316" strokeWidth={2} dot={false} />
        </ComposedChart>
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

      {/* Rolling 7-day volume + TRIMP */}
      <RollingVolume acts={allActs} />

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
