import { useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { MapContainer, TileLayer, Polyline } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  ComposedChart, Line, XAxis, YAxis, CartesianGrid,
  Legend, ResponsiveContainer, Area,
} from "recharts";
import { getActivities, getActivityFull, getDataPoints } from "../api/client";
import type { Activity, DataPoint } from "../types";
import { useUnits } from "../contexts/UnitsContext";

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtElapsed(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function fmtDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/** Binary-search nearest datapoint value at a given elapsed second. */
function interpVal(
  dps: DataPoint[],
  t0ms: number,
  targetS: number,
  key: "speed_m_s" | "heart_rate" | "altitude_m",
): number | null {
  if (!dps.length) return null;
  const targetMs = t0ms + targetS * 1000;
  let lo = 0, hi = dps.length - 1;
  while (lo < hi - 1) {
    const mid = (lo + hi) >> 1;
    if (new Date(dps[mid].timestamp).getTime() <= targetMs) lo = mid;
    else hi = mid;
  }
  return dps[lo][key] as number | null;
}

interface CompareRow {
  elapsed_s: number;
  pace_a: number | null;
  pace_b: number | null;
  hr_a: number | null;
  hr_b: number | null;
  elev_a: number | null;
  elev_b: number | null;
}

function buildCompareData(dpA: DataPoint[], dpB: DataPoint[]): CompareRow[] {
  if (!dpA.length && !dpB.length) return [];
  const t0A = dpA.length ? new Date(dpA[0].timestamp).getTime() : 0;
  const t0B = dpB.length ? new Date(dpB[0].timestamp).getTime() : 0;
  const durA = dpA.length ? (new Date(dpA[dpA.length - 1].timestamp).getTime() - t0A) / 1000 : 0;
  const durB = dpB.length ? (new Date(dpB[dpB.length - 1].timestamp).getTime() - t0B) / 1000 : 0;
  const maxDur = Math.max(durA, durB);

  const rows: CompareRow[] = [];
  for (let s = 0; s <= maxDur; s += 10) {
    const spdA = dpA.length && s <= durA ? interpVal(dpA, t0A, s, "speed_m_s") : null;
    const spdB = dpB.length && s <= durB ? interpVal(dpB, t0B, s, "speed_m_s") : null;
    rows.push({
      elapsed_s: s,
      pace_a: spdA && spdA > 0.3 ? Math.round((1000 / spdA) * 10) / 10 : null,
      pace_b: spdB && spdB > 0.3 ? Math.round((1000 / spdB) * 10) / 10 : null,
      hr_a:   dpA.length && s <= durA ? interpVal(dpA, t0A, s, "heart_rate") : null,
      hr_b:   dpB.length && s <= durB ? interpVal(dpB, t0B, s, "heart_rate") : null,
      elev_a: dpA.length && s <= durA ? interpVal(dpA, t0A, s, "altitude_m") : null,
      elev_b: dpB.length && s <= durB ? interpVal(dpB, t0B, s, "altitude_m") : null,
    });
  }
  return rows;
}

// ── activity selector ─────────────────────────────────────────────────────────

function ActivitySelector({
  label,
  colour,
  selectedId,
  onSelect,
  exclude,
  acts,
}: {
  label: string;
  colour: string;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  exclude: number | null;
  acts: Activity[];
}) {
  const { fmtDist } = useUnits();
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold" style={{ color: colour }}>{label}</label>
      <select
        className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
        value={selectedId ?? ""}
        onChange={(e) => onSelect(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">— pick a run —</option>
        {acts
          .filter((a) => a.id !== exclude)
          .map((a) => (
            <option key={a.id} value={a.id}>
              {new Date(a.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
              {" · "}{a.name ?? a.sport_type}
              {" · "}{fmtDist(a.distance_m)}
            </option>
          ))}
      </select>
    </div>
  );
}

// ── dual-track map ─────────────────────────────────────────────────────────────

function DualMap({
  trackA,
  trackB,
  colourA,
  colourB,
}: {
  trackA: [number, number][];
  trackB: [number, number][];
  colourA: string;
  colourB: string;
}) {
  const bounds = useMemo(() => {
    const all = [...trackA, ...trackB];
    if (!all.length) return null;
    return L.latLngBounds(all.map(([lat, lon]) => [lat, lon]));
  }, [trackA, trackB]);

  if (!bounds) return null;

  return (
    <div className="rounded-lg overflow-hidden border border-gray-200" style={{ height: 280 }}>
      <MapContainer
        bounds={bounds}
        boundsOptions={{ padding: [24, 24] }}
        style={{ height: "100%", width: "100%" }}
        zoomControl={true}
      >
        <TileLayer
          url="/api/tiles/light/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://openstreetmap.org">OSM</a>'
        />
        {trackA.length > 1 && <Polyline positions={trackA} color={colourA} weight={3} opacity={0.85} />}
        {trackB.length > 1 && <Polyline positions={trackB} color={colourB} weight={3} opacity={0.85} dashArray="8 4" />}
      </MapContainer>
    </div>
  );
}

// ── stats comparison table ────────────────────────────────────────────────────

function StatsTable({
  actA,
  actB,
  labelA,
  labelB,
  colourA,
  colourB,
}: {
  actA: Activity | null;
  actB: Activity | null;
  labelA: string;
  labelB: string;
  colourA: string;
  colourB: string;
}) {
  const { fmtDist, fmtPace } = useUnits();
  if (!actA && !actB) return null;

  const rows: { label: string; a: string; b: string }[] = [
    {
      label: "Date",
      a: actA ? new Date(actA.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—",
      b: actB ? new Date(actB.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—",
    },
    {
      label: "Distance",
      a: actA ? fmtDist(actA.distance_m) : "—",
      b: actB ? fmtDist(actB.distance_m) : "—",
    },
    {
      label: "Duration",
      a: actA ? fmtDuration(actA.duration_s) : "—",
      b: actB ? fmtDuration(actB.duration_s) : "—",
    },
    {
      label: "Avg Pace",
      a: actA ? fmtPace(actA.avg_pace_s_per_km) : "—",
      b: actB ? fmtPace(actB.avg_pace_s_per_km) : "—",
    },
    {
      label: "Avg HR",
      a: actA?.avg_hr ? `${actA.avg_hr} bpm` : "—",
      b: actB?.avg_hr ? `${actB.avg_hr} bpm` : "—",
    },
    {
      label: "Elevation ↑",
      a: actA ? `+${Math.round(actA.elevation_gain_m)} m` : "—",
      b: actB ? `+${Math.round(actB.elevation_gain_m)} m` : "—",
    },
  ];

  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-left text-xs text-gray-400 font-medium px-4 py-2 uppercase tracking-wide">Metric</th>
            <th className="text-center text-xs font-semibold px-4 py-2" style={{ color: colourA }}>{labelA}</th>
            <th className="text-center text-xs font-semibold px-4 py-2" style={{ color: colourB }}>{labelB}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-b border-gray-50 last:border-0">
              <td className="px-4 py-2 text-xs text-gray-500">{row.label}</td>
              <td className="px-4 py-2 text-center font-semibold text-gray-900 tabular-nums">{row.a}</td>
              <td className="px-4 py-2 text-center font-semibold text-gray-900 tabular-nums">{row.b}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── main Compare page ─────────────────────────────────────────────────────────

const COLOUR_A = "#3b82f6"; // blue
const COLOUR_B = "#f97316"; // orange

export default function Compare() {
  const [searchParams, setSearchParams] = useSearchParams();
  const idA = searchParams.get("a") ? Number(searchParams.get("a")) : null;
  const idB = searchParams.get("b") ? Number(searchParams.get("b")) : null;
  const { fmtPace } = useUnits();

  const [showHr, setShowHr] = useState(true);
  const [showElev, setShowElev] = useState(false);

  const { data: allActs = [] } = useQuery<Activity[]>({
    queryKey: ["activities"],
    queryFn: getActivities,
    staleTime: Infinity,
  });

  const { data: fullA } = useQuery({
    queryKey: ["activity-full", idA],
    queryFn: () => getActivityFull(idA!),
    enabled: idA != null,
    staleTime: Infinity,
  });
  const { data: dpA = [] } = useQuery<DataPoint[]>({
    queryKey: ["datapoints", idA],
    queryFn: () => getDataPoints(idA!),
    enabled: idA != null,
    staleTime: Infinity,
  });
  const { data: fullB } = useQuery({
    queryKey: ["activity-full", idB],
    queryFn: () => getActivityFull(idB!),
    enabled: idB != null,
    staleTime: Infinity,
  });
  const { data: dpB = [] } = useQuery<DataPoint[]>({
    queryKey: ["datapoints", idB],
    queryFn: () => getDataPoints(idB!),
    enabled: idB != null,
    staleTime: Infinity,
  });

  const actA: Activity | null = (fullA as any)?.activity ?? null;
  const actB: Activity | null = (fullB as any)?.activity ?? null;

  const trackA: [number, number][] = useMemo(
    () => ((fullA as any)?.track ?? []).map(([lat, lon]: number[]) => [lat, lon]),
    [fullA],
  );
  const trackB: [number, number][] = useMemo(
    () => ((fullB as any)?.track ?? []).map(([lat, lon]: number[]) => [lat, lon]),
    [fullB],
  );

  const chartData = useMemo(() => buildCompareData(dpA, dpB), [dpA, dpB]);

  const labelA = actA
    ? (actA.name ?? new Date(actA.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }))
    : "Run A";
  const labelB = actB
    ? (actB.name ?? new Date(actB.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }))
    : "Run B";

  const hasHr = chartData.some((r) => r.hr_a != null || r.hr_b != null);
  const hasElev = chartData.some((r) => r.elev_a != null || r.elev_b != null);

  return (
    <div className="p-4 max-w-5xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <Link to="/activities" className="text-xs text-blue-600 hover:underline">← Activities</Link>
          <h1 className="text-xl font-bold text-gray-900 mt-0.5">Compare Runs</h1>
        </div>
      </div>

      {/* Selectors */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
        <ActivitySelector
          label="Run A"
          colour={COLOUR_A}
          selectedId={idA}
          onSelect={(id) => setSearchParams(id ? { a: String(id), ...(idB ? { b: String(idB) } : {}) } : (idB ? { b: String(idB) } : {}))}
          exclude={idB}
          acts={allActs}
        />
        <ActivitySelector
          label="Run B"
          colour={COLOUR_B}
          selectedId={idB}
          onSelect={(id) => setSearchParams(id ? { ...(idA ? { a: String(idA) } : {}), b: String(id) } : (idA ? { a: String(idA) } : {}))}
          exclude={idA}
          acts={allActs}
        />
      </div>

      {/* Map */}
      {(trackA.length > 1 || trackB.length > 1) && (
        <DualMap trackA={trackA} trackB={trackB} colourA={COLOUR_A} colourB={COLOUR_B} />
      )}

      {/* Stats table */}
      <StatsTable actA={actA} actB={actB} labelA={labelA} labelB={labelB} colourA={COLOUR_A} colourB={COLOUR_B} />

      {/* Overlay chart */}
      {chartData.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          {/* Toolbar */}
          <div className="flex items-center gap-3 mb-3 flex-wrap">
            <h2 className="text-sm font-semibold text-gray-700 mr-2">Pace comparison</h2>
            {hasHr && (
              <button
                onClick={() => setShowHr((v) => !v)}
                className={`px-3 py-1 text-xs rounded-full border transition-colors ${showHr ? "text-white border-transparent bg-red-400" : "bg-white text-gray-600 border-gray-300"}`}
              >
                Heart Rate
              </button>
            )}
            {hasElev && (
              <button
                onClick={() => setShowElev((v) => !v)}
                className={`px-3 py-1 text-xs rounded-full border transition-colors ${showElev ? "text-white border-transparent bg-gray-400" : "bg-white text-gray-600 border-gray-300"}`}
              >
                Elevation
              </button>
            )}
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={chartData} margin={{ top: 4, right: 40, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="elevGradA" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={COLOUR_A} stopOpacity={0.2} />
                  <stop offset="95%" stopColor={COLOUR_A} stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="elevGradB" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={COLOUR_B} stopOpacity={0.2} />
                  <stop offset="95%" stopColor={COLOUR_B} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="elapsed_s" tickFormatter={fmtElapsed} minTickGap={60} tick={{ fontSize: 11 }} />
              {/* Pace axis — reversed (lower s/km = faster) */}
              <YAxis yAxisId="pace" orientation="left" reversed domain={["auto","auto"]} tickFormatter={(v) => fmtPace(v)} width={52} tick={{ fontSize: 10 }} />
              {/* HR axis */}
              {showHr && hasHr && (
                <YAxis yAxisId="hr" orientation="right" domain={["auto","auto"]} tick={{ fontSize: 10 }} width={40} />
              )}
              {/* Elevation — hidden axis, scale independent */}
              {showElev && hasElev && (
                <YAxis yAxisId="elev" orientation="right" domain={["auto","auto"]} tick={false} tickLine={false} axisLine={false} width={0} />
              )}
              <Legend wrapperStyle={{ fontSize: 12 }} />

              {/* Pace lines */}
              {idA && (
                <Line yAxisId="pace" type="monotone" dataKey="pace_a" dot={false} stroke={COLOUR_A} strokeWidth={2} name={`${labelA} pace`} connectNulls={false} isAnimationActive={false} />
              )}
              {idB && (
                <Line yAxisId="pace" type="monotone" dataKey="pace_b" dot={false} stroke={COLOUR_B} strokeWidth={2} strokeDasharray="6 3" name={`${labelB} pace`} connectNulls={false} isAnimationActive={false} />
              )}

              {/* HR lines */}
              {showHr && hasHr && idA && (
                <Line yAxisId="hr" type="monotone" dataKey="hr_a" dot={false} stroke={COLOUR_A} strokeWidth={1.5} strokeOpacity={0.6} name={`${labelA} HR`} connectNulls={false} isAnimationActive={false} />
              )}
              {showHr && hasHr && idB && (
                <Line yAxisId="hr" type="monotone" dataKey="hr_b" dot={false} stroke={COLOUR_B} strokeWidth={1.5} strokeOpacity={0.6} strokeDasharray="6 3" name={`${labelB} HR`} connectNulls={false} isAnimationActive={false} />
              )}

              {/* Elevation areas */}
              {showElev && hasElev && idA && (
                <Area yAxisId="elev" type="monotone" dataKey="elev_a" dot={false} stroke={COLOUR_A} fill="url(#elevGradA)" strokeWidth={1} name={`${labelA} elev`} connectNulls={false} isAnimationActive={false} />
              )}
              {showElev && hasElev && idB && (
                <Area yAxisId="elev" type="monotone" dataKey="elev_b" dot={false} stroke={COLOUR_B} fill="url(#elevGradB)" strokeWidth={1} name={`${labelB} elev`} connectNulls={false} isAnimationActive={false} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {(!idA && !idB) && (
        <div className="text-center text-gray-400 py-12 text-sm">
          Select two runs above to compare them.
        </div>
      )}
    </div>
  );
}
