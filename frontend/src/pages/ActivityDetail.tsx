import { useState, useEffect, useRef, useCallback, useMemo, type ReactNode } from "react";
import { useParams, Link, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getActivityFull, getDataPoints, getPhotos, getPersonalBests, getVdot, updateActivity, updateActivityShoe, getShoes, getActivities, refreshActivityFromCoros, deleteActivity } from "../api/client";
import { Activity, DataPoint, Photo, Shoe } from "../types";
import { useUnits } from "../contexts/UnitsContext";
import { formatDateLong, formatTime } from "../utils/dates";
import ActivityMap, { ActivityMapHandle } from "../components/ActivityMap";
import ActivityCharts from "../components/ActivityCharts";
import PhotoGallery from "../components/PhotoGallery";
import { PaceFraction } from "../components/PaceFraction";

interface Lap {
  id: number;
  lap_number: number;
  start_elapsed_s: number;
  end_elapsed_s: number;
  distance_m: number;
  duration_s: number;
  avg_hr: number | null;
  avg_pace_s_per_km: number | null;
  elevation_gain_m: number | null;
}

// formatPace is provided by useUnits()

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

const RPE_COLORS = ["", "text-blue-500", "text-green-500", "text-yellow-500", "text-orange-500", "text-red-500"];

const WEATHER_EMOJI: Record<string, string> = {
  "Clear": "☀️",
  "Partly cloudy": "⛅",
  "Overcast": "☁️",
  "Fog": "🌫️",
  "Rain": "🌧️",
  "Snow": "❄️",
  "Thunderstorm": "⛈️",
};

function WeatherBanner({ activity }: { activity: Activity }) {
  const { fmtTemp, fmtPrecip } = useUnits();
  if (!activity.weather_condition) return null;
  const emoji = WEATHER_EMOJI[activity.weather_condition] ?? "🌡️";
  const temp = activity.weather_temp_c != null ? fmtTemp(activity.weather_temp_c) : null;
  const feelsLike = activity.weather_feels_like_c != null &&
    Math.abs(activity.weather_feels_like_c - (activity.weather_temp_c ?? 0)) > 2
    ? `feels ${fmtTemp(activity.weather_feels_like_c)}` : null;
  const precip = activity.weather_precip_mm != null && activity.weather_precip_mm > 0.1
    ? fmtPrecip(activity.weather_precip_mm) : null;
  const cloud = activity.weather_cloud_pct != null ? `${activity.weather_cloud_pct}% cloud` : null;

  const parts = [temp, feelsLike, precip, cloud].filter(Boolean);

  return (
    <div className="flex items-center gap-3 pt-3 mt-3 border-t border-gray-100 text-sm text-gray-600 flex-wrap">
      <span className="text-lg leading-none">{emoji}</span>
      <span className="font-medium text-gray-700">{activity.weather_condition}</span>
      {parts.map((p, i) => (
        <span key={i} className="text-gray-500">{p}</span>
      ))}
    </div>
  );
}

function StatCell({ label, value, sub, valueColor }: { label: string; value: ReactNode; sub?: string; valueColor?: string }) {
  return (
    <div className="flex flex-col items-center px-4 first:pl-0 last:pr-0 border-l first:border-l-0 border-gray-200">
      <span className={`text-xl font-bold tabular-nums leading-tight ${valueColor ?? "text-gray-900"}`}>{value}</span>
      {sub && <span className="text-xs text-gray-400 leading-none mt-0.5">{sub}</span>}
      <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider mt-1">{label}</span>
    </div>
  );
}

/** Summary stats for the brush-selected range */
function RangeSummary({
  datapoints,
  range,
}: {
  datapoints: DataPoint[];
  range: [number, number];
}) {
  const { fmtDist, fmtPaceBoth, fmtElev } = useUnits();
  const slice = datapoints.slice(range[0], range[1] + 1);
  if (slice.length < 2) return null;

  const startDist = slice[0].distance_m ?? 0;
  const endDist = slice[slice.length - 1].distance_m ?? 0;
  const distM = endDist - startDist;

  const t0 = new Date(slice[0].timestamp).getTime();
  const t1 = new Date(slice[slice.length - 1].timestamp).getTime();
  const durationS = Math.round((t1 - t0) / 1000);

  const speeds = slice.filter((d) => d.speed_m_s && d.speed_m_s > 0).map((d) => d.speed_m_s!);
  const avgPace = speeds.length ? 1000 / (speeds.reduce((a, b) => a + b, 0) / speeds.length) : null;

  const hrs = slice.filter((d) => d.heart_rate).map((d) => d.heart_rate!);
  const avgHr = hrs.length ? Math.round(hrs.reduce((a, b) => a + b, 0) / hrs.length) : null;

  // Net elevation: end altitude minus start altitude (positive = gain, negative = loss)
  const altFirst = slice.find((d) => d.altitude_m != null)?.altitude_m ?? null;
  const altLast = [...slice].reverse().find((d) => d.altitude_m != null)?.altitude_m ?? null;
  const netElev = altFirst != null && altLast != null ? altLast - altFirst : null;

  return (
    <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 text-sm">
      <span className="font-medium text-orange-700 mr-3">Selected range:</span>
      <span className="text-gray-700 mr-4">{fmtDist(distM)}</span>
      <span className="text-gray-700 mr-4">{formatDuration(durationS)}</span>
      {avgPace && <span className="text-gray-700 mr-4">{fmtPaceBoth(avgPace)}</span>}
      {avgHr && <span className="text-gray-700 mr-4">{avgHr} bpm avg</span>}
      {netElev != null && (
        <span className={netElev >= 0 ? "text-green-700" : "text-red-600"}>
          {netElev >= 0 ? "+" : "−"}{fmtElev(Math.abs(netElev))}
        </span>
      )}
    </div>
  );
}

function LapTable({
  laps,
  activeLap,
  hoverLap,
  onLapClick,
  onLapHover,
}: {
  laps: Lap[];
  activeLap: number | null;
  hoverLap: number | null;
  onLapClick: (lap: Lap) => void;
  onLapHover: (lapNumber: number | null) => void;
}) {
  const { fmtPaceParts, fmtDist, system } = useUnits();
  if (!laps.length) return null;

  const distUnit = system === "imperial" ? "mi" : "km";

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3 sticky top-4">
      <h2 className="text-sm font-semibold text-gray-700 mb-2">Laps</h2>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 uppercase border-b border-gray-100">
            <th className="text-left pb-1.5">#</th>
            <th className="text-right pb-1.5 pl-2">Dist ({distUnit})</th>
            <th className="text-right pb-1.5 pl-2">Time</th>
            <th className="text-right pb-1.5 pl-2">/mi</th>
            <th className="text-right pb-1.5 pl-2">/km</th>
          </tr>
        </thead>
        <tbody>
          {laps.map((lap) => {
            const isActive = activeLap === lap.lap_number;
            const isHovered = hoverLap === lap.lap_number;
            const pace = fmtPaceParts(lap.avg_pace_s_per_km);
            return (
              <tr
                key={lap.id}
                onClick={() => onLapClick(lap)}
                onMouseEnter={() => onLapHover(lap.lap_number)}
                onMouseLeave={() => onLapHover(null)}
                className={`cursor-pointer border-b border-gray-50 transition-colors ${
                  isActive
                    ? "bg-orange-100 font-semibold"
                    : isHovered
                    ? "bg-orange-50"
                    : ""
                }`}
              >
                <td className="py-1.5 text-gray-500">{lap.lap_number}</td>
                <td className="py-1.5 text-right text-gray-800 tabular-nums pl-2">
                  {fmtDist(lap.distance_m).split(" ")[0]}
                </td>
                <td className="py-1.5 text-right text-gray-800 tabular-nums pl-2">
                  {formatDuration(Math.round(lap.duration_s))}
                </td>
                <td className="py-1.5 text-right text-gray-800 tabular-nums pl-2">{pace.mi}</td>
                <td className="py-1.5 text-right text-gray-800 tabular-nums pl-2">{pace.km}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── HR Zone breakdown ─────────────────────────────────────────────────────────

const HR_ZONES = [
  { label: "Easy (E)",       pctLo: 0,    pctHi: 0.79, colour: "#3b82f6" },
  { label: "Marathon (M)",   pctLo: 0.79, pctHi: 0.89, colour: "#22c55e" },
  { label: "Threshold (T)",  pctLo: 0.89, pctHi: 0.92, colour: "#f59e0b" },
  { label: "Hard (I+)",      pctLo: 0.92, pctHi: 1.0,  colour: "#ef4444" },
];

function HrZones({ datapoints, hrMax }: { datapoints: DataPoint[]; hrMax: number }) {
  const zoneTimes = useMemo(() => {
    const totals = HR_ZONES.map(() => 0);
    for (let i = 1; i < datapoints.length; i++) {
      const hr = datapoints[i].heart_rate;
      if (hr == null) continue;
      const dt = (new Date(datapoints[i].timestamp).getTime() - new Date(datapoints[i - 1].timestamp).getTime()) / 1000;
      if (dt <= 0 || dt > 60) continue;
      const pct = hr / hrMax;
      for (let z = HR_ZONES.length - 1; z >= 0; z--) {
        if (pct >= HR_ZONES[z].pctLo) { totals[z] += dt; break; }
      }
    }
    return totals;
  }, [datapoints, hrMax]);

  const total = zoneTimes.reduce((a, b) => a + b, 0);
  if (total < 30) return null;

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">
        HR Zones <span className="font-normal text-gray-400 text-xs">(HRmax {hrMax} bpm)</span>
      </h2>
      <div className="space-y-2">
        {HR_ZONES.map((zone, i) => {
          const pct = total > 0 ? (zoneTimes[i] / total) * 100 : 0;
          const mins = Math.floor(zoneTimes[i] / 60);
          const secs = Math.round(zoneTimes[i] % 60);
          return (
            <div key={zone.label} className="flex items-center gap-2">
              <span className="text-xs text-gray-500 w-28 flex-shrink-0">{zone.label}</span>
              <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${pct.toFixed(1)}%`, backgroundColor: zone.colour }}
                />
              </div>
              <span className="text-xs tabular-nums text-gray-600 w-20 text-right">
                {mins > 0 ? `${mins}m ${secs}s` : `${secs}s`}
                <span className="text-gray-400 ml-1">({pct.toFixed(0)}%)</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Best Efforts for this activity ────────────────────────────────────────────

type PBEntry = { rank: number; time_s: number; activity_id: number; start_elapsed_s: number; end_elapsed_s: number };
type PBData = Record<string, PBEntry[] | null>;

function fmtTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

const RANK_COLORS = ["text-yellow-500", "text-gray-400", "text-orange-400"];

function BestEfforts({ actId, onSegmentSelect }: { actId: number; onSegmentSelect: (start: number, end: number) => void }) {
  const { data: pbs } = useQuery<PBData>({
    queryKey: ["personal-bests"],
    queryFn: getPersonalBests,
    staleTime: Infinity,
  });

  const efforts = useMemo(() => {
    if (!pbs) return [];
    return Object.entries(pbs)
      .flatMap(([dist, entries]) =>
        (entries ?? []).filter((e) => e.activity_id === actId).map((e) => ({ dist, ...e }))
      )
      .sort((a, b) => {
        const distOrder = ["400m","800m","1k","1 mile","2 mile","3k","5k","8k","10k","15k","10 mile","20k","half","25k","30k","marathon"];
        return distOrder.indexOf(a.dist) - distOrder.indexOf(b.dist);
      });
  }, [pbs, actId]);

  if (!efforts.length) return null;

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">Best Efforts in This Run</h2>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        {efforts.map((e) => (
          <button
            key={e.dist}
            onClick={() => onSegmentSelect(e.start_elapsed_s, e.end_elapsed_s)}
            className="flex items-center justify-between text-xs rounded hover:bg-blue-50 px-1.5 py-1 transition-colors text-left"
          >
            <span className="text-gray-600 font-medium w-16">{e.dist}</span>
            <span className="font-mono text-gray-900">{fmtTime(e.time_s)}</span>
            <span className={`ml-1.5 font-semibold ${RANK_COLORS[e.rank - 1] ?? "text-gray-400"}`}>
              #{e.rank}
            </span>
          </button>
        ))}
      </div>
      <p className="text-[10px] text-gray-400 mt-2">Click a segment to zoom the chart</p>
    </div>
  );
}

export default function ActivityDetail() {
  const { id } = useParams<{ id: string }>();
  const actId = Number(id);
  const navigate = useNavigate();

  const { data: activities = [] } = useQuery<Activity[]>({
    queryKey: ["activities"],
    queryFn: getActivities,
    staleTime: 60_000,
  });

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger while typing in an input, textarea, or select
      const tag = (e.target as HTMLElement).tagName.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;

      const idx = activities.findIndex((a) => a.id === actId);
      if (idx === -1) return;

      if (e.key === "ArrowRight" && idx < activities.length - 1) {
        navigate(`/activities/${activities[idx + 1].id}`);
      } else if (e.key === "ArrowLeft" && idx > 0) {
        navigate(`/activities/${activities[idx - 1].id}`);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activities, actId, navigate]);

  const [searchParams] = useSearchParams();
  const segStart = searchParams.get("seg_start") ? parseFloat(searchParams.get("seg_start")!) : null;
  const segEnd = searchParams.get("seg_end") ? parseFloat(searchParams.get("seg_end")!) : null;
  const [brushRange, setBrushRange] = useState<[number, number] | null>(null);
  const [activeLap, setActiveLap] = useState<number | null>(null);
  const [hoverLap, setHoverLap] = useState<number | null>(null);
  const mapRef = useRef<ActivityMapHandle>(null);
  const { fmtDist, fmtElev } = useUnits();

  // Combined endpoint: activity + laps + track in one shot
  const { data: full, isLoading: fullLoading } = useQuery<{
    activity: Activity;
    laps: Lap[];
    track: [number, number, number | null][];
  }>({
    queryKey: ["activity-full", actId],
    queryFn: () => getActivityFull(actId),
    staleTime: Infinity,  // activity data never changes
  });

  const act = full?.activity;
  const laps = full?.laps ?? [];
  const track = full?.track;
  const shoes = (full as any)?.shoes as { id: number; name: string; brand: string | null }[] | undefined;

  const { data: datapoints = [], isLoading: dpLoading } = useQuery<DataPoint[]>({
    queryKey: ["datapoints", actId],
    queryFn: () => getDataPoints(actId),
    staleTime: Infinity,  // GPS points never change after import
  });

  const handleHoverIndex = useCallback((idx: number | null) => {
    if (idx == null) { mapRef.current?.updateHover(null, null); return; }
    const dp = datapoints[idx];
    if (dp?.lat != null && dp?.lon != null) mapRef.current?.updateHover(dp.lat, dp.lon);
    else mapRef.current?.updateHover(null, null);
  }, [datapoints]);

  const { data: photos = [] } = useQuery<Photo[]>({
    queryKey: ["photos", actId],
    queryFn: () => getPhotos(actId),
    staleTime: Infinity,
  });

  const { data: vdot } = useQuery<{ hr_max: number; hr_rest: number }>({
    queryKey: ["vdot"],
    queryFn: getVdot,
    staleTime: Infinity,
  });
  const hrMax = vdot?.hr_max ?? 185;

  const queryClient = useQueryClient();

  const { data: allShoes = [] } = useQuery<Shoe[]>({
    queryKey: ["shoes"],
    queryFn: getShoes,
  });

  const currentShoeId = shoes && shoes.length > 0 ? shoes[0].id : null;

  // Active shoes + currently-assigned shoe (even if retired, so it shows correctly)
  const activeShoes = allShoes.filter(
    (s) => !s.retired || s.id === currentShoeId
  );

  const shoeMutation = useMutation({
    mutationFn: (shoeId: number | null) => updateActivityShoe(actId, shoeId),
    // The dropdown reads its value from full.shoes (activity-{id}.json), which
    // the backend rebuilds asynchronously. Patch the cache so the selection
    // shows instantly — same approach as editMutation/corosRefreshMutation. We
    // deliberately do NOT re-invalidate ["activity-full"] in onSettled, since
    // that refetch would race the async rebuild and clobber this value.
    onMutate: async (shoeId: number | null) => {
      await queryClient.cancelQueries({ queryKey: ["activity-full", actId] });
      const previous = queryClient.getQueryData(["activity-full", actId]);
      const picked = shoeId == null ? null : allShoes.find((s) => s.id === shoeId);
      const newShoes = picked
        ? [{ id: picked.id, name: picked.name, brand: picked.brand }]
        : [];
      queryClient.setQueryData(["activity-full", actId], (old: any) =>
        old ? { ...old, shoes: newShoes } : old,
      );
      return { previous };
    },
    onError: (_err, _shoeId, ctx: any) => {
      if (ctx?.previous) queryClient.setQueryData(["activity-full", actId], ctx.previous);
    },
    onSettled: () => {
      // shoes.json is rebuilt synchronously by the backend, so these are safe.
      queryClient.invalidateQueries({ queryKey: ["shoes"] });
      queryClient.invalidateQueries({ queryKey: ["activities"] });
    },
  });

  const corosRefreshMutation = useMutation({
    mutationFn: () => refreshActivityFromCoros(actId),
    onSuccess: (updatedActivity) => {
      // Optimistically patch the cached activity-full data so UI updates instantly
      // (static JSON rebuild happens async in background)
      queryClient.setQueryData(["activity-full", actId], (old: any) =>
        old ? { ...old, activity: { ...old.activity, ...updatedActivity } } : old
      );
      queryClient.invalidateQueries({ queryKey: ["activities"] });
    },
  });

  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesDraft, setNotesDraft] = useState("");
  const nameInputRef = useRef<HTMLInputElement>(null);
  const notesTextareaRef = useRef<HTMLTextAreaElement>(null);

  const editMutation = useMutation({
    mutationFn: (data: { name?: string | null; notes?: string | null }) =>
      updateActivity(actId, data),
    onSuccess: (updatedActivity) => {
      queryClient.setQueryData(["activity-full", actId], (old: any) =>
        old ? { ...old, activity: { ...old.activity, ...updatedActivity } } : old
      );
      queryClient.invalidateQueries({ queryKey: ["activities"] });
    },
  });

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const deleteMutation = useMutation({
    mutationFn: () => deleteActivity(actId),
    onSuccess: () => {
      // Drop this activity's cached detail and refresh the list, then leave.
      queryClient.removeQueries({ queryKey: ["activity-full", actId] });
      queryClient.removeQueries({ queryKey: ["datapoints", actId] });
      queryClient.invalidateQueries({ queryKey: ["activities"] });
      navigate("/activities");
    },
  });

  function startEditName() {
    setNameDraft(act?.name ?? "");
    setEditingName(true);
    setTimeout(() => nameInputRef.current?.focus(), 0);
  }

  function saveName() {
    const trimmed = nameDraft.trim();
    editMutation.mutate({ name: trimmed || null });
    setEditingName(false);
  }

  function startEditNotes() {
    setNotesDraft(act?.notes ?? "");
    setEditingNotes(true);
    setTimeout(() => notesTextareaRef.current?.focus(), 0);
  }

  function saveNotes() {
    editMutation.mutate({ notes: notesDraft.trim() || null });
    setEditingNotes(false);
  }

  // Convert elapsed seconds → nearest datapoint index
  function elapsedToIdx(targetS: number): number {
    if (!datapoints.length) return 0;
    const t0 = new Date(datapoints[0].timestamp).getTime();
    let best = 0, bestDiff = Infinity;
    for (let i = 0; i < datapoints.length; i++) {
      const diff = Math.abs((new Date(datapoints[i].timestamp).getTime() - t0) / 1000 - targetS);
      if (diff < bestDiff) { bestDiff = diff; best = i; }
    }
    return best;
  }

  // Auto-zoom to personal-best segment when seg_start/seg_end query params are present
  useEffect(() => {
    if (!datapoints.length || segStart === null) return;
    setBrushRange([elapsedToIdx(segStart), elapsedToIdx(segEnd ?? segStart)]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datapoints.length > 0]);

  function handleBestEffortSelect(startS: number, endS: number) {
    setActiveLap(null);
    setBrushRange([elapsedToIdx(startS), elapsedToIdx(endS)]);
  }

  function handleLapClick(lap: Lap) {
    if (activeLap === lap.lap_number) {
      setActiveLap(null);
      setBrushRange(null);
    } else {
      setActiveLap(lap.lap_number);
      setBrushRange([elapsedToIdx(lap.start_elapsed_s), elapsedToIdx(lap.end_elapsed_s)]);
    }
  }

  // Index range of the currently-hovered lap, used to paint a transient highlight
  // band on the charts and an in-place segment on the map (no zoom / no re-fit).
  const hoverLapObj = hoverLap !== null ? laps.find((l) => l.lap_number === hoverLap) : null;
  const hoverRange: [number, number] | null = hoverLapObj
    ? [elapsedToIdx(hoverLapObj.start_elapsed_s), elapsedToIdx(hoverLapObj.end_elapsed_s)]
    : null;

  if (fullLoading) {
    return <div className="p-6 text-gray-500">Loading activity…</div>;
  }
  if (!act) {
    return (
      <div className="p-6 text-gray-500">
        Activity not found.{" "}
        <Link to="/activities" className="text-blue-600 hover:underline">
          Back to list
        </Link>
      </div>
    );
  }

  const startDate = formatDateLong(act.started_at);
  const startTime = formatTime(act.started_at);
  const finishTime = formatTime(
    new Date(new Date(act.started_at).getTime() + act.duration_s * 1000).toISOString()
  );

  return (
    <div className="p-4 max-w-5xl mx-auto space-y-4">
      {/* Unified activity banner */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {/* Top: title + meta */}
        <div className="flex items-start justify-between px-5 pt-4 pb-3">
          <div>
            <Link to="/activities" className="text-xs text-blue-600 hover:underline mb-1.5 block">
              ← Activities
            </Link>
            {editingName ? (
              <form
                onSubmit={(e) => { e.preventDefault(); saveName(); }}
                className="flex items-center gap-2"
              >
                <input
                  ref={nameInputRef}
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  onBlur={saveName}
                  onKeyDown={(e) => { if (e.key === "Escape") setEditingName(false); }}
                  placeholder={act.sport_type.replace(/_/g, " ")}
                  className="text-xl font-bold text-gray-900 leading-tight border-b-2 border-blue-400 outline-none bg-transparent w-full capitalize"
                />
              </form>
            ) : (
              <h1
                onClick={startEditName}
                className="text-xl font-bold text-gray-900 capitalize leading-tight cursor-pointer hover:text-blue-700 transition-colors"
                title="Click to edit title"
              >
                {act.name ?? act.sport_type.replace(/_/g, " ")}
              </h1>
            )}
            <p className="text-sm text-gray-500 mt-0.5">
              {startDate} · {startTime} – {finishTime}
            </p>
            {(act.sunrise || act.sunset) && (
              <p className="text-xs text-gray-400 mt-0.5 flex items-center gap-3">
                {act.sunrise && <span>🌅 {formatTime(act.sunrise)}</span>}
                {act.sunset && <span>🌇 {formatTime(act.sunset)}</span>}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-[11px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full capitalize">
              {act.source.replace(/_/g, " ")}
            </span>
            {act.source === "coros" && (
              <button
                onClick={() => corosRefreshMutation.mutate()}
                disabled={corosRefreshMutation.isPending}
                className="text-[11px] bg-green-50 text-green-600 hover:bg-green-100 disabled:opacity-50 px-2 py-0.5 rounded-full transition-colors"
                title="Re-fetch notes and RPE from Coros"
              >
                {corosRefreshMutation.isPending ? "Refreshing…" : "Refresh from Coros"}
              </button>
            )}
            {corosRefreshMutation.isSuccess && (
              <span className="text-[11px] text-green-600">Updated</span>
            )}
            {corosRefreshMutation.isError && (
              <span className="text-[11px] text-red-500">Refresh failed</span>
            )}
            <Link
              to={`/compare?a=${actId}`}
              className="text-[11px] bg-blue-50 text-blue-600 hover:bg-blue-100 px-2 py-0.5 rounded-full transition-colors"
            >
              Compare →
            </Link>
            <button
              onClick={() => setConfirmingDelete(true)}
              className="text-[11px] bg-red-50 text-red-600 hover:bg-red-100 px-2 py-0.5 rounded-full transition-colors"
              title="Delete this activity"
            >
              Delete
            </button>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-gray-100 mx-5" />

        {/* Stats row */}
        <div className="flex items-start gap-0 px-5 py-3 flex-wrap">
          <StatCell label="Distance" value={fmtDist(act.distance_m)} />
          <StatCell label="Time" value={formatDuration(act.duration_s)} />
          <StatCell label="Avg Pace" value={<PaceFraction sPerKm={act.avg_pace_s_per_km} className="text-base" />} />
          <div className="flex flex-col items-center px-4 first:pl-0 last:pr-0 border-l first:border-l-0 border-gray-200">
            <div className="flex flex-col items-center leading-tight tabular-nums">
              <span className="text-xl font-bold text-green-600">+{fmtElev(act.elevation_gain_m)}</span>
              <span className="text-base font-semibold text-red-500">
                −{act.elevation_loss_m != null ? fmtElev(act.elevation_loss_m) : "—"}
              </span>
            </div>
            <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider mt-1">Elevation</span>
          </div>
          {act.avg_hr && <StatCell label="Avg HR" value={`${act.avg_hr}`} sub="bpm" />}
          {act.rpe != null && act.rpe > 0 && (
            <StatCell
              label="Effort"
              value={["", "Very Easy", "Easy", "Moderate", "Hard", "Maximum"][act.rpe]}
              sub={`RPE ${act.rpe}/5`}
              valueColor={RPE_COLORS[act.rpe]}
            />
          )}
        </div>
        <div className="px-5 pb-4">
          <WeatherBanner activity={act} />
          <div className="flex items-center gap-2 pt-2 mt-1">
            <span className="text-base leading-none">👟</span>
            <select
              value={currentShoeId ?? ""}
              disabled={shoeMutation.isPending}
              onChange={(e) => {
                const val = e.target.value;
                shoeMutation.mutate(val === "" ? null : parseInt(val, 10));
              }}
              className="text-sm border border-gray-200 rounded px-2 py-0.5 bg-white text-gray-700 disabled:opacity-50"
            >
              <option value="">No shoe</option>
              {activeShoes.map((s) => (
                <option key={s.id} value={s.id}>{s.name}{s.brand ? ` (${s.brand})` : ""}</option>
              ))}
            </select>
            {shoeMutation.isError && (
              <span className="text-xs text-red-500">Failed to save</span>
            )}
          </div>
        </div>
      </div>

      {/* Notes — editable */}
      {editingNotes ? (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
          <textarea
            ref={notesTextareaRef}
            value={notesDraft}
            onChange={(e) => setNotesDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setEditingNotes(false);
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) saveNotes();
            }}
            rows={4}
            placeholder="Add notes…"
            className="w-full text-sm text-gray-700 bg-transparent outline-none resize-y leading-relaxed"
          />
          <div className="flex items-center justify-end gap-2 mt-2">
            <span className="text-[10px] text-gray-400 mr-auto">Cmd+Enter to save · Esc to cancel</span>
            <button
              onClick={() => setEditingNotes(false)}
              className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1"
            >
              Cancel
            </button>
            <button
              onClick={saveNotes}
              className="text-xs bg-amber-600 text-white hover:bg-amber-700 px-3 py-1 rounded transition-colors"
            >
              Save
            </button>
          </div>
        </div>
      ) : act.notes ? (
        <div
          onClick={startEditNotes}
          className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 cursor-pointer hover:border-amber-300 transition-colors group"
          title="Click to edit notes"
        >
          <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{act.notes}</p>
          <span className="text-[10px] text-amber-400 group-hover:text-amber-600 transition-colors">Click to edit</span>
        </div>
      ) : (
        <button
          onClick={startEditNotes}
          className="w-full text-left text-sm text-gray-400 hover:text-gray-600 border border-dashed border-gray-200 hover:border-gray-300 rounded-lg px-4 py-3 transition-colors"
        >
          + Add notes…
        </button>
      )}

      {/* Main body: laps sidebar + map/charts */}
      {/* On mobile: charts first (order-1), laps below (order-2). On md+: laps left, charts right. */}
      <div className="flex flex-col md:flex-row gap-4 items-start">
        {/* Laps — below on mobile, left column on desktop */}
        {laps.length > 0 && (
          <div className="order-2 md:order-1 w-full md:w-56 md:flex-shrink-0">
            <LapTable
              laps={laps}
              activeLap={activeLap}
              hoverLap={hoverLap}
              onLapClick={handleLapClick}
              onLapHover={setHoverLap}
            />
          </div>
        )}

        {/* Map + range summary + charts — top on mobile, right on desktop */}
        <div className="order-1 md:order-2 flex-1 min-w-0 space-y-4">
          {/* Map */}
          {!track ? (
            <div className="h-64 bg-gray-100 rounded-lg flex items-center justify-center text-gray-400">
              Loading GPS data…
            </div>
          ) : (
            <ActivityMap
              ref={mapRef}
              datapoints={datapoints}
              preloadedTrack={track}
              photos={photos}
              highlightRange={brushRange}
              previewRange={hoverRange}
            />
          )}

          {/* Range summary */}
          {brushRange && datapoints.length > 0 && (
            <RangeSummary datapoints={datapoints} range={brushRange} />
          )}

          {/* Charts */}
          {!dpLoading && datapoints.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h2 className="text-lg font-semibold text-gray-800 mb-3">
                Analysis
                <span className="text-xs font-normal text-gray-400 ml-2">
                  {datapoints.length.toLocaleString()} data points
                </span>
              </h2>
              <ActivityCharts
                datapoints={datapoints}
                externalRange={brushRange}
                highlightRange={hoverRange}
                onRangeChange={(start, end) => { setActiveLap(null); setBrushRange([start, end]); }}
                onRangeClear={() => { setActiveLap(null); setBrushRange(null); }}
                onHoverIndex={handleHoverIndex}
              />
            </div>
          )}

          {/* Best efforts for this activity */}
          {datapoints.length > 0 && (
            <BestEfforts actId={actId} onSegmentSelect={handleBestEffortSelect} />
          )}

          {/* HR zone breakdown */}
          {datapoints.some((d) => d.heart_rate != null) && (
            <HrZones datapoints={datapoints} hrMax={hrMax} />
          )}
        </div>
      </div>

      {/* Photos */}
      {photos.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h2 className="text-lg font-semibold text-gray-800 mb-3">Photos</h2>
          <PhotoGallery photos={photos} />
        </div>
      )}

      {/* Delete confirmation */}
      {confirmingDelete && (
        <div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/40 p-4"
          onClick={() => !deleteMutation.isPending && setConfirmingDelete(false)}
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-sm w-full p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-semibold text-gray-900">Delete activity?</h2>
            <p className="text-sm text-gray-600 mt-2">
              This permanently removes{" "}
              <span className="font-medium text-gray-800">
                {act.name ?? act.sport_type.replace(/_/g, " ")}
              </span>{" "}
              ({startDate}) and all its GPS data, laps, and photos. This cannot be undone.
            </p>
            {deleteMutation.isError && (
              <p className="text-sm text-red-600 mt-2">Delete failed — please try again.</p>
            )}
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setConfirmingDelete(false)}
                disabled={deleteMutation.isPending}
                className="text-sm text-gray-600 hover:text-gray-800 disabled:opacity-50 px-3 py-1.5"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate()}
                disabled={deleteMutation.isPending}
                className="text-sm bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 px-4 py-1.5 rounded transition-colors"
              >
                {deleteMutation.isPending ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
