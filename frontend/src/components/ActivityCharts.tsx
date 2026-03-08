import { useMemo, useState, useEffect, useRef } from "react";
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
  ReferenceArea,
} from "recharts";
import { DataPoint } from "../types";
import { useUnits } from "../contexts/UnitsContext";

interface Props {
  datapoints: DataPoint[];
  externalRange?: [number, number] | null;
  onRangeChange?: (startIdx: number, endIdx: number) => void;
  onRangeClear?: () => void;
  onHoverIndex?: (idx: number | null) => void;
}

type MainOverlay = "pace" | "gap" | "hr" | "elevation" | "cadence" | "power";
type DynOverlay = "vert_osc" | "stride_length" | "vert_ratio" | "gct" | "flight_time";

const MAIN_OVERLAYS: { key: MainOverlay; label: string; colour: string }[] = [
  { key: "pace",      label: "Pace",        colour: "#3b82f6" },
  { key: "gap",       label: "GAP",         colour: "#06b6d4" },
  { key: "hr",        label: "Heart Rate",  colour: "#ef4444" },
  { key: "elevation", label: "Elevation",   colour: "#94a3b8" },
  { key: "cadence",   label: "Cadence",     colour: "#f59e0b" },
  { key: "power",     label: "Power",       colour: "#8b5cf6" },
];

const DYN_OVERLAYS: { key: DynOverlay; label: string; colour: string }[] = [
  { key: "vert_osc",      label: "Vert. Osc.",     colour: "#06b6d4" },
  { key: "stride_length", label: "Stride Length",  colour: "#d946ef" },
  { key: "vert_ratio",    label: "Vert. Ratio",    colour: "#ec4899" },
  { key: "gct",           label: "Ground Contact", colour: "#f97316" },
  { key: "flight_time",   label: "Flight Time",    colour: "#84cc16" },
];

function formatElapsed(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface ChartRow {
  idx: number;
  elapsed_s: number;
  pace: number | null;
  gap: number | null;
  hr: number | null;
  elevation: number | null;
  cadence: number | null;
  power: number | null;
  vert_osc: number | null;
  stride_length: number | null;
  vert_ratio: number | null;
  gct: number | null;
  flight_time: number | null;
}

/** Minetti 2002: metabolic cost of running at grade g (W/kg/m). g in [-0.45, 0.45]. */
function minettCost(g: number): number {
  const g2 = g * g, g3 = g2 * g, g4 = g2 * g2, g5 = g4 * g;
  return 155.4 * g5 - 30.4 * g4 - 43.3 * g3 + 46.3 * g2 + 19.5 * g + 3.6;
}
const C0 = minettCost(0); // 3.6 W/kg/m — flat running cost

export default function ActivityCharts({ datapoints, externalRange, onRangeChange, onRangeClear, onHoverIndex }: Props) {
  const { fmtPace, fmtElev } = useUnits();
  const [activeMain, setActiveMain] = useState<Set<MainOverlay>>(
    new Set(["pace", "hr", "elevation"])
  );
  const [activeDyn, setActiveDyn] = useState<Set<DynOverlay>>(
    new Set(["vert_osc", "gct"])
  );
  const [zoomedRange, setZoomedRange] = useState<[number, number] | null>(null);

  // Sync externally-set range (e.g. lap click) into chart zoom
  useEffect(() => {
    setZoomedRange(externalRange ?? null);
  }, [externalRange]);

  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dragEnd, setDragEnd] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const isDraggingRef = useRef(false);

  // DOM tooltip + crosshair refs — updated directly without React re-renders
  const mainTipRef  = useRef<HTMLDivElement>(null);
  const dynTipRef   = useRef<HTMLDivElement>(null);
  const mainLineRef = useRef<HTMLDivElement>(null);
  const dynLineRef  = useRef<HTMLDivElement>(null);

  // Unit formatters — kept in a ref so the tooltip builder always has current values
  const fmtRef = useRef<Record<string, (v: number) => string>>({});

  const data: ChartRow[] = useMemo(() => {
    if (!datapoints.length) return [];
    const n = datapoints.length;
    const t0 = new Date(datapoints[0].timestamp).getTime();

    // Smooth altitude with ±5-sample window to reduce GPS noise before computing grade
    const W = 5;
    const smoothAlt: (number | null)[] = datapoints.map((_, i) => {
      const lo = Math.max(0, i - W), hi = Math.min(n - 1, i + W);
      const vals: number[] = [];
      for (let j = lo; j <= hi; j++) {
        if (datapoints[j].altitude_m != null) vals.push(datapoints[j].altitude_m!);
      }
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    });

    return datapoints.map((dp, idx) => {
      const elapsed_s = Math.round(
        (new Date(dp.timestamp).getTime() - t0) / 1000
      );
      const pace =
        dp.speed_m_s && dp.speed_m_s > 0.5
          ? Math.round((1000 / dp.speed_m_s) * 10) / 10
          : null;

      // Grade-adjusted pace using Minetti 2002
      let gap: number | null = null;
      if (pace != null && idx > 0 && idx < n - 1) {
        const look = Math.min(4, Math.floor(W / 2));
        const lo = Math.max(0, idx - look), hi = Math.min(n - 1, idx + look);
        const alt0 = smoothAlt[lo], alt1 = smoothAlt[hi];
        const dist0 = datapoints[lo].distance_m, dist1 = datapoints[hi].distance_m;
        if (alt0 != null && alt1 != null && dist0 != null && dist1 != null) {
          const dDist = dist1 - dist0;
          if (dDist >= 2) {
            const g = Math.max(-0.45, Math.min(0.45, (alt1 - alt0) / dDist));
            const cg = minettCost(g);
            if (cg > 0) {
              const raw = Math.round(pace * (C0 / cg) * 10) / 10;
              // Clamp to [0.5×, 2×] actual pace to avoid chart blow-out on extreme grades
              gap = Math.max(pace * 0.5, Math.min(pace * 2, raw));
            }
          }
        }
      }

      const flight_time =
        dp.cadence && dp.cadence > 0 && dp.stance_time_ms != null
          ? Math.max(0, Math.round(60000 / dp.cadence - dp.stance_time_ms))
          : null;
      return {
        idx,
        elapsed_s,
        pace,
        gap,
        hr: dp.heart_rate ?? null,
        elevation: dp.altitude_m ?? null,
        cadence: dp.cadence ?? null,
        power: dp.power_w ?? null,
        vert_osc: dp.vertical_oscillation_mm ?? null,
        stride_length: dp.stride_length_m != null ? Math.round(dp.stride_length_m * 100) : null,
        vert_ratio: dp.vertical_ratio ?? null,
        gct: dp.stance_time_ms ?? null,
        flight_time,
      };
    });
  }, [datapoints]);

  // Update formatter ref every render (fmtPace/fmtElev may depend on unit setting)
  fmtRef.current = {
    pace:          (v) => fmtPace(v),
    gap:           (v) => fmtPace(v),
    elevation:     (v) => fmtElev(v),
    hr:            (v) => `${v} bpm`,
    cadence:       (v) => `${v} spm`,
    power:         (v) => `${v} W`,
    vert_osc:      (v) => `${v.toFixed(1)} mm`,
    stride_length: (v) => `${v} cm`,
    vert_ratio:    (v) => `${v.toFixed(1)} %`,
    gct:           (v) => `${v.toFixed(0)} ms`,
    flight_time:   (v) => `${v.toFixed(0)} ms`,
  };

  const offset = zoomedRange?.[0] ?? 0;
  const displayData = zoomedRange ? data.slice(zoomedRange[0], zoomedRange[1] + 1) : data;

  const hasPower = datapoints.some((dp) => dp.power_w !== null);
  const hasAltitude = datapoints.some((dp) => dp.altitude_m != null);
  const hasDynamics = datapoints.some(
    (dp) => dp.vertical_oscillation_mm != null || dp.stance_time_ms != null
  );

  function zoomOut() {
    setZoomedRange(null);
    onRangeClear?.();
  }

  function commitZoom() {
    if (dragStart === null || dragEnd === null) return;
    const left = Math.min(dragStart, dragEnd);
    const right = Math.max(dragStart, dragEnd);
    if (left === right) return;

    let startIdx = 0;
    let endIdx = displayData.length - 1;
    for (let i = 0; i < displayData.length; i++) {
      if (displayData[i].elapsed_s >= left) { startIdx = i; break; }
    }
    for (let i = displayData.length - 1; i >= 0; i--) {
      if (displayData[i].elapsed_s <= right) { endIdx = i; break; }
    }
    if (endIdx <= startIdx) return;

    const absStart = offset + startIdx;
    const absEnd = offset + endIdx;
    setZoomedRange([absStart, absEnd]);
    onRangeChange?.(absStart, absEnd);
  }

  // Directly write tooltip content into a DOM ref — no React re-render needed
  function showTip(
    el: HTMLDivElement | null,
    label: number,
    payload: any[],
    coord: { x: number; y: number },
    containerWidth: number,
  ) {
    if (!el || isDraggingRef.current) { hideTip(el); return; }
    const fmt = fmtRef.current;
    const rows = payload
      .filter((p) => p.value != null)
      .map(
        (p) =>
          `<div style="color:${p.color}" class="flex justify-between gap-3 text-xs">` +
          `<span>${p.name}</span>` +
          `<span class="font-semibold">${fmt[p.dataKey]?.(p.value) ?? p.value}</span>` +
          `</div>`
      )
      .join("");

    el.innerHTML =
      `<div class="text-xs font-medium text-gray-500 mb-1">${formatElapsed(label)}</div>` + rows;
    el.style.visibility = "visible";

    // Position: prefer right of cursor, flip to left near edge
    const tipWidth = 160;
    const leftX = coord.x + 20 + tipWidth > containerWidth ? coord.x - tipWidth - 20 : coord.x + 20;
    el.style.left = `${leftX}px`;
    el.style.top  = `${Math.max(0, coord.y - 30)}px`;
  }

  function hideTip(el: HTMLDivElement | null) {
    if (el) el.style.visibility = "hidden";
  }

  function showLine(el: HTMLDivElement | null, x: number) {
    if (!el) return;
    el.style.visibility = "visible";
    el.style.left = `${x}px`;
  }

  function hideLine(el: HTMLDivElement | null) {
    if (el) el.style.visibility = "hidden";
  }

  // Build a synthetic Recharts-style payload from a data row for cross-chart tooltips
  function buildCrossPayload(
    row: ChartRow,
    overlays: { key: string; label: string; colour: string }[],
  ) {
    return overlays
      .filter((o) => row[o.key as keyof ChartRow] != null)
      .map((o) => ({ name: o.label, dataKey: o.key, value: row[o.key as keyof ChartRow] as number, color: o.colour }));
  }

  if (!data.length) return null;

  const availableMain = MAIN_OVERLAYS.filter((o) =>
    !(o.key === "power" && !hasPower) && !(o.key === "gap" && !hasAltitude)
  );
  const visibleMain = availableMain.filter((o) => activeMain.has(o.key));
  const paceActive = activeMain.has("pace");

  const refLeft  = dragStart !== null && dragEnd !== null ? Math.min(dragStart, dragEnd) : null;
  const refRight = dragStart !== null && dragEnd !== null ? Math.max(dragStart, dragEnd) : null;

  // Shared mouse handlers — mutate ref to avoid stale closure in Recharts callbacks
  function handleMouseDown(e: any) {
    const label = e?.activeLabel;
    if (label == null) return;
    setDragStart(label);
    setDragEnd(label);
    setIsDragging(true);
    isDraggingRef.current = true;
  }

  function handleMouseUp() {
    if (isDraggingRef.current) {
      commitZoom();
      setDragStart(null);
      setDragEnd(null);
      setIsDragging(false);
      isDraggingRef.current = false;
    }
  }

  function handleMouseLeave() {
    onHoverIndex?.(null);
    hideTip(mainTipRef.current);
    hideTip(dynTipRef.current);
    hideLine(mainLineRef.current);
    hideLine(dynLineRef.current);
    if (isDraggingRef.current) {
      setDragStart(null);
      setDragEnd(null);
      setIsDragging(false);
      isDraggingRef.current = false;
    }
  }

  return (
    <div className="space-y-4">
      {/* ── Main chart toolbar ── */}
      <div className="flex items-center gap-2 flex-wrap">
        {availableMain.map((o) => (
          <button
            key={o.key}
            onClick={() => setActiveMain((prev) => {
              const next = new Set(prev);
              if (next.has(o.key)) next.delete(o.key); else next.add(o.key);
              return next;
            })}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              activeMain.has(o.key)
                ? "text-white border-transparent"
                : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
            }`}
            style={activeMain.has(o.key) ? { backgroundColor: o.colour, borderColor: o.colour } : {}}
          >
            {o.label}
          </button>
        ))}

        {zoomedRange && (
          <button
            onClick={zoomOut}
            className="ml-auto px-2.5 py-1 text-xs rounded border bg-gray-50 text-gray-600 border-gray-300 hover:bg-gray-100"
          >
            Reset zoom
          </button>
        )}
      </div>

      {/* ── Main chart ── */}
      <div className="relative">
        {/* DOM tooltip — positioned absolutely, updated without React re-render */}
        <div
          ref={mainTipRef}
          className="absolute z-10 bg-white border border-gray-200 rounded shadow-md p-2.5 pointer-events-none"
          style={{ visibility: "hidden", minWidth: 140 }}
        />
        {/* Crosshair vertical line */}
        <div
          ref={mainLineRef}
          className="absolute top-0 bottom-0 pointer-events-none"
          style={{ width: 1, borderLeft: "1.5px dashed #9ca3af", zIndex: 9, visibility: "hidden" }}
        />
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart
            data={displayData}
            margin={{ top: 4, right: 16, left: 0, bottom: 0 }}
            style={{ cursor: isDragging ? "col-resize" : "crosshair" }}
            onMouseDown={handleMouseDown}
            onMouseMove={(e: any) => {
              const label = e?.activeLabel;
              const idx   = e?.activeTooltipIndex;
              const coord = e?.activeCoordinate;
              if (!isDraggingRef.current) {
                onHoverIndex?.(idx != null ? offset + idx : null);
                const cw = e.chartX != null ? e.chartX + 200 : 600;
                if (coord && e.activePayload?.length) {
                  showTip(mainTipRef.current, label, e.activePayload, coord, cw);
                }
                // Cross-chart: show dyn data in the dynamics tooltip
                if (coord && idx != null && displayData[idx] && hasDynamics) {
                  const crossPayload = buildCrossPayload(
                    displayData[idx],
                    DYN_OVERLAYS.filter((o) => activeDyn.has(o.key)),
                  );
                  if (crossPayload.length) showTip(dynTipRef.current, label, crossPayload, { x: coord.x, y: 8 }, cw);
                  else hideTip(dynTipRef.current);
                }
                if (coord) {
                  showLine(mainLineRef.current, coord.x);
                  showLine(dynLineRef.current, coord.x);
                }
              } else {
                hideTip(mainTipRef.current);
                hideTip(dynTipRef.current);
                hideLine(mainLineRef.current);
                hideLine(dynLineRef.current);
                if (label != null) setDragEnd(label);
              }
            }}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseLeave}
          >
            <defs>
              <linearGradient id="elevGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#94a3b8" stopOpacity={0.5} />
                <stop offset="95%" stopColor="#94a3b8" stopOpacity={0.05} />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="elapsed_s"
              tickFormatter={formatElapsed}
              minTickGap={60}
              tick={{ fontSize: 11 }}
              allowDataOverflow
            />
            {/* Left axis always rendered at fixed width=52 so plot area stays constant
                regardless of which overlays are active — keeps crosshair x aligned
                with the dynamics chart below */}
            <YAxis
              yAxisId="pace"
              orientation="left"
              reversed
              domain={["auto", "auto"]}
              tickFormatter={(v) => fmtPace(v)}
              tick={paceActive ? { fontSize: 10 } : false}
              tickLine={paceActive}
              axisLine={paceActive}
              width={52}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={["auto", "auto"]}
              tick={{ fontSize: 10 }}
              width={40}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />

            {visibleMain.map((o) =>
              o.key === "elevation" ? (
                <Area
                  key={o.key}
                  yAxisId="right"
                  type="monotone"
                  dataKey="elevation"
                  stroke="#94a3b8"
                  fill="url(#elevGradient)"
                  strokeWidth={1.5}
                  name="Elevation"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ) : (
                <Line
                  key={o.key}
                  yAxisId={o.key === "pace" || o.key === "gap" ? "pace" : "right"}
                  type="monotone"
                  dataKey={o.key}
                  dot={false}
                  stroke={o.colour}
                  strokeWidth={1.5}
                  strokeDasharray={o.key === "gap" ? "4 2" : undefined}
                  name={o.label}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              )
            )}

            {isDragging && refLeft !== null && refRight !== null && refLeft !== refRight && (
              <ReferenceArea
                yAxisId="right"
                x1={refLeft}
                x2={refRight}
                fill="#3b82f6"
                fillOpacity={0.15}
                stroke="#3b82f6"
                strokeOpacity={0.4}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* ── Running dynamics chart ── */}
      {hasDynamics && (
        <div className="border-t pt-4">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className="text-xs font-semibold text-gray-500 mr-1">Running Dynamics</span>
            {DYN_OVERLAYS.map((o) => (
              <button
                key={o.key}
                onClick={() => setActiveDyn((prev) => {
                  const next = new Set(prev);
                  if (next.has(o.key)) next.delete(o.key); else next.add(o.key);
                  return next;
                })}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  activeDyn.has(o.key)
                    ? "text-white border-transparent"
                    : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
                }`}
                style={activeDyn.has(o.key) ? { backgroundColor: o.colour, borderColor: o.colour } : {}}
              >
                {o.label}
              </button>
            ))}
          </div>

          <div className="relative">
            <div
              ref={dynTipRef}
              className="absolute z-10 bg-white border border-gray-200 rounded shadow-md p-2.5 pointer-events-none"
              style={{ visibility: "hidden", minWidth: 140 }}
            />
            <div
              ref={dynLineRef}
              className="absolute top-0 bottom-0 pointer-events-none"
              style={{ width: 1, borderLeft: "1.5px dashed #9ca3af", zIndex: 9, visibility: "hidden" }}
            />
            <ResponsiveContainer width="100%" height={180}>
              <ComposedChart
                data={displayData}
                margin={{ top: 4, right: 16, left: 0, bottom: 0 }}
                onMouseMove={(e: any) => {
                  const label = e?.activeLabel;
                  const idx   = e?.activeTooltipIndex;
                  const coord = e?.activeCoordinate;
                  if (coord && !isDraggingRef.current) {
                    onHoverIndex?.(idx != null ? offset + idx : null);
                    const cw = e.chartX != null ? e.chartX + 200 : 600;
                    if (e.activePayload?.length) {
                      showTip(dynTipRef.current, label, e.activePayload, coord, cw);
                    }
                    // Cross-chart: show main data in the analysis tooltip
                    if (idx != null && displayData[idx]) {
                      const crossPayload = buildCrossPayload(
                        displayData[idx],
                        availableMain.filter((o) => activeMain.has(o.key)),
                      );
                      if (crossPayload.length) showTip(mainTipRef.current, label, crossPayload, { x: coord.x, y: 8 }, cw);
                      else hideTip(mainTipRef.current);
                    }
                    showLine(dynLineRef.current, coord.x);
                    showLine(mainLineRef.current, coord.x);
                  } else {
                    hideTip(dynTipRef.current);
                    hideTip(mainTipRef.current);
                    hideLine(dynLineRef.current);
                    hideLine(mainLineRef.current);
                  }
                }}
                onMouseLeave={() => {
                  onHoverIndex?.(null);
                  hideTip(dynTipRef.current);
                  hideTip(mainTipRef.current);
                  hideLine(dynLineRef.current);
                  hideLine(mainLineRef.current);
                }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="elapsed_s"
                  tickFormatter={formatElapsed}
                  minTickGap={60}
                  tick={{ fontSize: 11 }}
                  allowDataOverflow
                />
                {/* Each active dynamic metric gets its own YAxis with its own domain
                    so small differences (e.g. ground contact 240–260 ms) fill the chart.
                    Primary axis (first active metric) is visible at width=52 to keep
                    the plot area width identical to the main chart (crosshair alignment).
                    Additional axes are hidden with width=0 — independent scale, no space. */}
                {(() => {
                  const activeDynArr = DYN_OVERLAYS.filter((o) => activeDyn.has(o.key));
                  if (activeDynArr.length === 0) {
                    return <YAxis yAxisId="placeholder" orientation="left" width={52} tick={false} tickLine={false} axisLine={false} />;
                  }
                  return activeDynArr.map((o, idx) => (
                    <YAxis
                      key={o.key}
                      yAxisId={o.key}
                      orientation="left"
                      domain={["auto", "auto"]}
                      tick={idx === 0 ? { fontSize: 10 } : false}
                      tickLine={idx === 0}
                      axisLine={idx === 0}
                      width={idx === 0 ? 52 : 0}
                    />
                  ));
                })()}
                {/* Hidden right spacer — same width as main chart's right axis */}
                <YAxis
                  yAxisId="dyn-right"
                  orientation="right"
                  width={40}
                  tick={false}
                  tickLine={false}
                  axisLine={false}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />

                {DYN_OVERLAYS.filter((o) => activeDyn.has(o.key)).map((o) => (
                  <Line
                    key={o.key}
                    yAxisId={o.key}
                    type="monotone"
                    dataKey={o.key}
                    dot={false}
                    stroke={o.colour}
                    strokeWidth={1.5}
                    name={o.label}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
