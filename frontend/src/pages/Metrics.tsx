import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { getVdot, getPersonalBests, getMetrics } from "../api/client";
import { useUnits } from "../contexts/UnitsContext";

function fmtTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

type PBEntry = {
  rank: number;
  time_s: number;
  activity_id: number;
  start_elapsed_s: number;
  end_elapsed_s: number;
};
type PBData = Record<string, PBEntry[] | null>;

const PB_DISTANCES = [
  "400m", "800m", "1k", "1 mile", "2 mile", "3k", "5k", "8k",
  "10k", "15k", "10 mile", "20k", "half", "25k", "30k", "marathon",
] as const;

const ZONE_DEFS = [
  { key: "easy",      label: "Easy",      loKey: "easy_hi", hiKey: "easy_lo", color: "bg-green-400",  textColor: "text-green-700",  desc: "Conversational aerobic base" },
  { key: "marathon",  label: "Marathon",  loKey: "marathon", hiKey: null,      color: "bg-blue-400",   textColor: "text-blue-700",   desc: "Goal marathon pace" },
  { key: "threshold", label: "Threshold", loKey: "threshold", hiKey: null,     color: "bg-yellow-400", textColor: "text-yellow-700", desc: "Comfortably hard, sustained" },
  { key: "interval",  label: "Interval",  loKey: "interval", hiKey: null,      color: "bg-orange-400", textColor: "text-orange-700", desc: "~VO₂max effort, 3-5 min reps" },
  { key: "reps",      label: "Repetition", loKey: "repetition", hiKey: null,   color: "bg-red-500",    textColor: "text-red-700",    desc: "Speed/form, short reps" },
] as const;

export default function Fitness() {
  const { fmtPace } = useUnits();

  const { data: vdotData, isLoading: vdotLoading } = useQuery({
    queryKey: ["vdot"],
    queryFn: getVdot,
    staleTime: Infinity,  // static file — only changes after a write
  });

  const [expandedDist, setExpandedDist] = useState<string | null>(null);
  const { data: pbData, isLoading: pbLoading } = useQuery<PBData>({
    queryKey: ["personal-bests"],
    queryFn: getPersonalBests,
    staleTime: Infinity,  // static file — only changes after a write
  });

  const { data: metricsData } = useQuery({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    staleTime: Infinity,
  });

  const eddington = metricsData?.eddington;
  const yearly = metricsData?.yearly;

  const zones = vdotData?.pace_zones_s_per_km;

  return (
    <div className="p-4 max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Metrics</h1>

      {/* VDOT hero */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <div className="text-xs text-gray-400 uppercase tracking-widest mb-1">Current VDOT</div>
            {vdotLoading ? (
              <div className="text-gray-400 text-sm">Calculating…</div>
            ) : vdotData?.vdot ? (
              <>
                <div className="text-6xl font-black text-blue-600 leading-none">{vdotData.vdot}</div>
                <div className="text-xs text-gray-400 mt-1">
                  Based on {vdotData.sample_size} runs · last 28 days
                  {vdotData.based_on_activity_id && (
                    <Link
                      to={`/activities/${vdotData.based_on_activity_id}`}
                      className="ml-2 text-blue-500 hover:underline"
                    >
                      source activity →
                    </Link>
                  )}
                </div>
              </>
            ) : (
              <div className="text-gray-400">No data — run more to get a VDOT estimate</div>
            )}
          </div>

          {/* Race predictions */}
          {vdotData?.race_predictions_s && (
            <div className="bg-gray-50 rounded-lg p-4 min-w-[180px]">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Race Predictions</div>
              <div className="space-y-1.5">
                {Object.entries(vdotData.race_predictions_s).map(([dist, s]) => (
                  <div key={dist} className="flex items-center justify-between gap-6">
                    <span className="text-sm text-gray-500 uppercase w-16">{dist}</span>
                    <span className="text-sm font-bold text-gray-800 font-mono">
                      {s ? fmtTime(s as number) : "–"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Pace zones */}
      {zones && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">Training Pace Zones</h2>
          <div className="space-y-3">
            {ZONE_DEFS.map((z) => {
              const lo = zones[z.loKey as keyof typeof zones] as number;
              const hi = z.hiKey ? zones[z.hiKey as keyof typeof zones] as number : null;
              const paceStr = hi ? `${fmtPace(hi)} – ${fmtPace(lo)}` : fmtPace(lo);
              return (
                <div key={z.key} className="flex items-center gap-4">
                  <div className={`w-3 h-3 rounded-full flex-shrink-0 ${z.color}`} />
                  <div className="w-24 text-sm font-semibold text-gray-700">{z.label}</div>
                  <div className="text-sm font-mono text-gray-800 w-36">{paceStr}</div>
                  <div className="text-xs text-gray-400 hidden sm:block">{z.desc}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Personal bests */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">Personal Bests</h2>
        {pbLoading ? (
          <div className="text-sm text-gray-400">Loading…</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-xs text-gray-400 uppercase border-b border-gray-100">
                <th className="text-left pb-2">Distance</th>
                <th className="text-right pb-2">Best Time</th>
                <th className="text-right pb-2">Pace</th>
                <th className="text-right pb-2"></th>
              </tr>
            </thead>
            <tbody>
              {PB_DISTANCES.map((label) => {
                const entries = pbData?.[label] ?? null;
                const best = entries?.[0] ?? null;
                const distMap: Record<string, number> = {
                  "400m": 400, "800m": 800, "1k": 1000, "1 mile": 1609,
                  "2 mile": 3219, "3k": 3000, "5k": 5000, "8k": 8000,
                  "10k": 10000, "15k": 15000, "10 mile": 16093, "20k": 20000,
                  "half": 21097, "25k": 25000, "30k": 30000, "marathon": 42195,
                };
                const distM = distMap[label];
                const pacePerKm = best && distM ? best.time_s / (distM / 1000) : null;
                const isExpanded = expandedDist === label;
                const hasHistory = entries && entries.length > 1;
                return (
                  <>
                    <tr
                      key={label}
                      className={`border-b border-gray-50 ${hasHistory ? "cursor-pointer hover:bg-gray-50" : ""}`}
                      onClick={() => hasHistory && setExpandedDist(isExpanded ? null : label)}
                    >
                      <td className="py-2.5 text-sm font-medium text-gray-700 flex items-center gap-1">
                        {label}
                        {hasHistory && (
                          <span className="text-[10px] text-gray-400 ml-1">
                            {isExpanded ? "▲" : `▼ ${entries!.length}`}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 text-right text-sm font-bold text-gray-900 font-mono">
                        {best ? fmtTime(best.time_s) : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="py-2.5 text-right text-sm text-gray-500 font-mono">
                        {pacePerKm ? fmtPace(pacePerKm) : ""}
                      </td>
                      <td className="py-2.5 text-right">
                        {best && (
                          <Link
                            to={`/activities/${best.activity_id}?seg_start=${best.start_elapsed_s}&seg_end=${best.end_elapsed_s}`}
                            className="text-xs text-blue-500 hover:text-blue-700 hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            View →
                          </Link>
                        )}
                      </td>
                    </tr>
                    {isExpanded && entries && entries.slice(1).map((e) => {
                      const pace = distM ? e.time_s / (distM / 1000) : null;
                      return (
                        <tr key={`${label}-${e.rank}`} className="bg-gray-50 border-b border-gray-50">
                          <td className="py-1.5 pl-5 text-xs text-gray-400">#{e.rank}</td>
                          <td className="py-1.5 text-right text-xs text-gray-600 font-mono">{fmtTime(e.time_s)}</td>
                          <td className="py-1.5 text-right text-xs text-gray-400 font-mono">
                            {pace ? fmtPace(pace) : ""}
                          </td>
                          <td className="py-1.5 text-right">
                            <Link
                              to={`/activities/${e.activity_id}?seg_start=${e.start_elapsed_s}&seg_end=${e.end_elapsed_s}`}
                              className="text-xs text-blue-400 hover:text-blue-600 hover:underline"
                            >
                              View →
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Eddington Number */}
      {eddington && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">Eddington Number</h2>
          <div className="flex items-start gap-8 flex-wrap">
            <div>
              <div className="text-6xl font-black text-blue-600 leading-none">{eddington.current_e}</div>
              <div className="text-xs text-gray-400 mt-1">
                {eddington.next_e_gap === 0
                  ? `Achieved! Run ${eddington.current_e + 1} mi on ${eddington.current_e + 1} more days for E${eddington.current_e + 1}`
                  : `${eddington.next_e_gap} more run${eddington.next_e_gap === 1 ? "" : "s"} of ≥${eddington.current_e + 1} mi for E${eddington.current_e + 1}`}
              </div>
            </div>
            {eddington.history.length > 1 && (
              <div className="flex-1 min-w-[280px] h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={eddington.history} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(0, 7)} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                    <Tooltip formatter={(v: number) => [`E${v}`, "Eddington"]} labelFormatter={(l: string) => l} />
                    <Area type="stepAfter" dataKey="e" stroke="#3b82f6" fill="#dbeafe" strokeWidth={2} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Yearly Mileage Overlay */}
      {yearly?.years && Object.keys(yearly.years).length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">Annual Mileage by Week</h2>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="week" type="number" domain={[1, 53]} tickCount={14} tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} unit=" km" />
                <Tooltip formatter={(v: number, name: string) => [`${v.toFixed(1)} km`, name]} />
                <Legend />
                {Object.entries(yearly.years).map(([year, weeks], i) => {
                  const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];
                  return (
                    <Line
                      key={year}
                      data={weeks as { week: number; km: number }[]}
                      dataKey="km"
                      name={year}
                      stroke={COLORS[i % COLORS.length]}
                      strokeWidth={2}
                      dot={false}
                      type="monotone"
                    />
                  );
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
