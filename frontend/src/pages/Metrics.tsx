import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { getPersonalBests, getMetrics } from "../api/client";
import { CHART_COLORS } from "../config";
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

export default function Fitness() {
  const { fmtPace, system } = useUnits();

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

  return (
    <div className="p-4 max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Metrics</h1>

      {/* Yearly Cumulative Mileage Overlay — moved to top */}
      {yearly?.years && Object.keys(yearly.years).length > 0 && (() => {
        const COLORS = CHART_COLORS;
        const distUnit = system === "imperial" ? "mi" : "km";
        const toDisplayDist = (km: number) => system === "imperial" ? km / 1.60934 : km;
        const years = Object.keys(yearly.years);

        const MONTH_STARTS = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];
        const MONTH_LABELS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
        const tickFormatter = (day: number) => {
          const idx = MONTH_STARTS.indexOf(day);
          return idx >= 0 ? MONTH_LABELS[idx] : "";
        };

        const yearDayMaps: Record<string, Record<number, number>> = {};
        for (const [year, entries] of Object.entries(yearly.years)) {
          const sorted = (entries as { day: number; km: number }[]).slice().sort((a, b) => a.day - b.day);
          let cumulative = 0;
          const dayMap: Record<number, number> = {};
          for (const { day, km } of sorted) {
            cumulative += km;
            dayMap[day] = Math.round(toDisplayDist(cumulative) * 10) / 10;
          }
          const firstDay = sorted[0]?.day ?? 1;
          const lastDay = sorted[sorted.length - 1]?.day ?? firstDay;
          let lastVal = 0;
          for (let d = firstDay; d <= lastDay; d++) {
            if (dayMap[d] !== undefined) lastVal = dayMap[d];
            else dayMap[d] = lastVal;
          }
          yearDayMaps[year] = dayMap;
        }

        const unifiedData = Array.from({ length: 366 }, (_, i) => {
          const day = i + 1;
          const entry: Record<string, number | null> = { day };
          for (const year of years) entry[year] = yearDayMaps[year][day] ?? null;
          return entry;
        });

        const CumulativeTooltip = ({ active, payload, label }: any) => {
          if (!active || !payload?.length) return null;
          const visible = payload.filter((p: any) => p.value !== null && p.value !== undefined);
          if (!visible.length) return null;
          const d = new Date(2026, 0, label);
          const dateLabel = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
          return (
            <div className="bg-white border border-gray-200 rounded px-3 py-2 text-xs shadow">
              <div className="font-semibold text-gray-600 mb-1">{dateLabel}</div>
              {visible.map((p: any) => (
                <div key={p.name} style={{ color: p.stroke }}>{p.name}: {p.value.toFixed(1)} {distUnit}</div>
              ))}
            </div>
          );
        };

        return (
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">Cumulative Annual Mileage</h2>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={unifiedData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="day" type="number" domain={[1, 366]} ticks={MONTH_STARTS} tickFormatter={tickFormatter} tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} unit={` ${distUnit}`} />
                  <Tooltip content={<CumulativeTooltip />} />
                  <Legend />
                  {years.map((year, i) => (
                    <Line key={year} dataKey={year} name={year} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} type="stepAfter" connectNulls={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        );
      })()}

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

    </div>
  );
}
