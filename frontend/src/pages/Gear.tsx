import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";
import { getShoes, getShoesTimeline, createShoe, updateShoe, setDefaultShoe } from "../api/client";
import { useUnits } from "../contexts/UnitsContext";
import { SHOE_RETIREMENT_MI, SHOE_RETIREMENT_KM, CHART_COLORS } from "../config";
import { formatDateShort, formatDateMonthDay } from "../utils/dates";

type DailyRow = { date: string } & Record<string, number | null>;

interface Shoe {
  id: number;
  name: string;
  brand: string | null;
  retired: boolean;
  is_default: boolean;
  notes: string | null;
  retirement_threshold_km: number;
  total_distance_km: number;
  activity_ids?: number[];
  first_used?: string | null;
  years?: number[];
}

function MileageBar({ used, limit }: { used: number; limit: number }) {
  const pct = Math.min((used / limit) * 100, 100);
  const color = pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-yellow-400" : "bg-green-500";
  return (
    <div className="w-full bg-gray-100 rounded-full h-2 mt-1">
      <div className={`${color} h-2 rounded-full transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

const KM_PER_MI = 1.60934;

type YearFilter = "all" | number;

function buildChartData(daily: DailyRow[], shoes: Shoe[], year: YearFilter) {
  const rows = year === "all"
    ? daily
    : daily.filter((r) => r.date.startsWith(`${year}-`));
  const visibleShoeIds = new Set<number>();
  for (const shoe of shoes) {
    const k = String(shoe.id);
    if (rows.some((r) => r[k] != null)) visibleShoeIds.add(shoe.id);
  }
  return { rows, visibleShoeIds };
}

function ShoeTimelineChart({
  shoes, daily, year,
}: { shoes: Shoe[]; daily: DailyRow[]; year: YearFilter }) {
  const { system, fmtShoe } = useUnits();
  const distUnit = system === "imperial" ? "mi" : "km";

  const { rows, visibleShoeIds } = useMemo(
    () => buildChartData(daily, shoes, year),
    [daily, shoes, year],
  );
  if (rows.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 text-center text-sm text-gray-400">
        No mileage in this period.
      </div>
    );
  }

  const visibleShoes = shoes.filter((s) => visibleShoeIds.has(s.id));
  const tickFormatter = year === "all" ? formatDateShort : formatDateMonthDay;
  const toDisplay = (km: number) => (system === "imperial" ? km / KM_PER_MI : km);

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-3">
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10 }}
              tickFormatter={tickFormatter}
              minTickGap={32}
            />
            <YAxis
              tick={{ fontSize: 10 }}
              tickFormatter={(v: number) => `${Math.round(toDisplay(v))}`}
              unit={` ${distUnit}`}
              width={64}
            />
            <Tooltip
              labelFormatter={(d: string) => formatDateShort(d)}
              formatter={(v: number, name: string) => {
                const shoe = shoes.find((s) => String(s.id) === name);
                return [fmtShoe(v), shoe?.name ?? name];
              }}
            />
            {year === "all" &&
              visibleShoes.map((shoe, i) => (
                <ReferenceLine
                  key={`limit-${shoe.id}`}
                  y={shoe.retirement_threshold_km}
                  stroke={CHART_COLORS[i % CHART_COLORS.length]}
                  strokeDasharray="2 4"
                  strokeOpacity={0.3}
                />
              ))}
            {visibleShoes.map((shoe, i) => (
              <Line
                key={shoe.id}
                type="monotone"
                dataKey={String(shoe.id)}
                name={String(shoe.id)}
                stroke={CHART_COLORS[i % CHART_COLORS.length]}
                strokeWidth={2}
                strokeDasharray={shoe.retired ? "4 2" : undefined}
                strokeOpacity={shoe.retired ? 0.5 : 1}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {visibleShoes.map((shoe, i) => (
          <div key={shoe.id} className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-0.5"
              style={{
                background: CHART_COLORS[i % CHART_COLORS.length],
                opacity: shoe.retired ? 0.5 : 1,
              }}
            />
            <span className={shoe.retired ? "text-gray-400" : "text-gray-700"}>
              {shoe.name}
              {shoe.retired ? " (retired)" : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Gear() {
  const qc = useQueryClient();
  const { system, fmtShoe } = useUnits();
  const defaultThreshold = system === "imperial" ? String(SHOE_RETIREMENT_MI) : String(SHOE_RETIREMENT_KM);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", brand: "", retirement_threshold: defaultThreshold });

  const { data: shoes = [] } = useQuery<Shoe[]>({
    queryKey: ["shoes"],
    queryFn: getShoes,
  });
  const { data: daily = [] } = useQuery<DailyRow[]>({
    queryKey: ["shoes-timeline"],
    queryFn: getShoesTimeline,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const thresholdKm = system === "imperial"
        ? parseFloat(form.retirement_threshold) * KM_PER_MI
        : parseFloat(form.retirement_threshold);
      return createShoe({
        name: form.name,
        brand: form.brand || null,
        retirement_threshold_km: thresholdKm,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["shoes"] });
      qc.invalidateQueries({ queryKey: ["shoes-timeline"] });
      setForm({ name: "", brand: "", retirement_threshold: defaultThreshold });
      setShowForm(false);
    },
  });

  const retireMutation = useMutation({
    mutationFn: (id: number) => updateShoe(id, { retired: true }),
    // Optimistically move the shoe to the Retired section immediately; the
    // chart's line-termination reconciles when shoes-timeline.json refetches.
    onMutate: async (id: number) => {
      await qc.cancelQueries({ queryKey: ["shoes"] });
      const previous = qc.getQueryData<Shoe[]>(["shoes"]);
      qc.setQueryData<Shoe[]>(["shoes"], (old) =>
        old?.map((s) =>
          s.id === id ? { ...s, retired: true, is_default: false } : s,
        ),
      );
      return { previous };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(["shoes"], ctx.previous);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["shoes"] });
      qc.invalidateQueries({ queryKey: ["shoes-timeline"] });
    },
  });

  const defaultMutation = useMutation({
    mutationFn: (shoeId: number | null) => setDefaultShoe(shoeId),
    // Flip the star instantly; the backend rebuilds shoes.json synchronously
    // so the onSettled refetch is safe and confirms the optimistic state.
    onMutate: async (shoeId: number | null) => {
      await qc.cancelQueries({ queryKey: ["shoes"] });
      const previous = qc.getQueryData<Shoe[]>(["shoes"]);
      qc.setQueryData<Shoe[]>(["shoes"], (old) =>
        old?.map((s) => ({ ...s, is_default: s.id === shoeId })),
      );
      return { previous };
    },
    onError: (_err, _shoeId, ctx) => {
      if (ctx?.previous) qc.setQueryData(["shoes"], ctx.previous);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["shoes"] }),
  });

  // ── Rename / re-brand a shoe ──────────────────────────────────────────────
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ name: "", brand: "" });

  const editMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { name: string; brand: string | null } }) =>
      updateShoe(id, data),
    onMutate: async ({ id, data }) => {
      await qc.cancelQueries({ queryKey: ["shoes"] });
      const previous = qc.getQueryData<Shoe[]>(["shoes"]);
      qc.setQueryData<Shoe[]>(["shoes"], (old) =>
        old?.map((s) => (s.id === id ? { ...s, name: data.name, brand: data.brand } : s)),
      );
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(["shoes"], ctx.previous);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["shoes"] }),
  });

  function startEdit(shoe: Shoe) {
    setEditingId(shoe.id);
    setEditForm({ name: shoe.name, brand: shoe.brand ?? "" });
  }

  function saveEdit(id: number) {
    const name = editForm.name.trim();
    if (!name) return; // name is required
    editMutation.mutate({ id, data: { name, brand: editForm.brand.trim() || null } });
    setEditingId(null);
  }

  const renderEditor = (id: number) => (
    <div className="flex-1 flex items-center gap-2 flex-wrap">
      <input
        autoFocus
        className="border border-gray-300 rounded px-2 py-1 text-sm flex-1 min-w-[8rem]"
        value={editForm.name}
        placeholder="Name"
        onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
        onKeyDown={(e) => {
          if (e.key === "Enter") saveEdit(id);
          if (e.key === "Escape") setEditingId(null);
        }}
      />
      <input
        className="border border-gray-300 rounded px-2 py-1 text-sm w-32"
        value={editForm.brand}
        placeholder="Brand"
        onChange={(e) => setEditForm((f) => ({ ...f, brand: e.target.value }))}
        onKeyDown={(e) => {
          if (e.key === "Enter") saveEdit(id);
          if (e.key === "Escape") setEditingId(null);
        }}
      />
      <button
        onClick={() => saveEdit(id)}
        disabled={!editForm.name.trim()}
        className="text-xs bg-blue-600 text-white px-3 py-1 rounded disabled:opacity-50"
      >
        Save
      </button>
      <button
        onClick={() => setEditingId(null)}
        className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1"
      >
        Cancel
      </button>
    </div>
  );

  const active = shoes.filter((s) => !s.retired);
  const retired = shoes.filter((s) => s.retired);

  const [yearFilter, setYearFilter] = useState<YearFilter>("all");
  const yearOptions = useMemo(() => {
    const all = new Set<number>();
    for (const s of shoes) for (const y of s.years ?? []) all.add(y);
    return [...all].sort((a, b) => b - a);
  }, [shoes]);
  const hasTimelineData = daily.length > 0;

  return (
    <div className="p-4 max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-xl font-bold text-gray-800">Gear</h1>
        <div className="flex items-center gap-2">
          {hasTimelineData && (
            <select
              value={yearFilter === "all" ? "all" : String(yearFilter)}
              onChange={(e) =>
                setYearFilter(e.target.value === "all" ? "all" : Number(e.target.value))
              }
              className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
            >
              <option value="all">All time</option>
              {yearOptions.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          )}
          <button
            onClick={() => setShowForm((v) => !v)}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            + Add Shoe
          </button>
        </div>
      </div>

      {hasTimelineData && <ShoeTimelineChart shoes={shoes} daily={daily} year={yearFilter} />}

      {showForm && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3">
          <h2 className="text-sm font-semibold text-gray-700">New Shoe</h2>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Name *</label>
              <input
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Endorphin Speed 3"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Brand</label>
              <input
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                value={form.brand}
                onChange={(e) => setForm((f) => ({ ...f, brand: e.target.value }))}
                placeholder="e.g. Saucony"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">
                Retirement threshold ({system === "imperial" ? "mi" : "km"})
              </label>
              <input
                type="number"
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                value={form.retirement_threshold}
                onChange={(e) => setForm((f) => ({ ...f, retirement_threshold: e.target.value }))}
              />
            </div>
          </div>
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => setShowForm(false)}
              className="px-3 py-1.5 text-sm text-gray-600 border border-gray-300 rounded"
            >
              Cancel
            </button>
            <button
              onClick={() => createMutation.mutate()}
              disabled={!form.name || createMutation.isPending}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
            >
              Save
            </button>
          </div>
        </div>
      )}

      {active.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm divide-y divide-gray-100">
          {active.map((shoe) => (
            <div key={shoe.id} className="flex items-center p-4 hover:bg-gray-50 transition-colors">
              {editingId === shoe.id ? (
                renderEditor(shoe.id)
              ) : (
                <>
                  <button
                    onClick={() =>
                      defaultMutation.mutate(shoe.is_default ? null : shoe.id)
                    }
                    aria-label={shoe.is_default ? "Default shoe" : "Set as default"}
                    className={`mr-3 text-xl leading-none transition-colors ${
                      shoe.is_default ? "text-yellow-500" : "text-gray-300 hover:text-yellow-400"
                    }`}
                    disabled={defaultMutation.isPending}
                  >
                    {shoe.is_default ? "★" : "☆"}
                  </button>
                  <Link
                    to={`/activities?shoe=${shoe.id}`}
                    className="flex-1 min-w-0"
                  >
                    <div className="font-medium text-gray-800">{shoe.name}</div>
                    {shoe.brand && <div className="text-xs text-gray-400">{shoe.brand}</div>}
                    <MileageBar used={shoe.total_distance_km} limit={shoe.retirement_threshold_km} />
                  </Link>
                  <div className="text-right ml-4 flex-shrink-0">
                    <div className="text-sm font-mono text-gray-700">
                      {fmtShoe(shoe.total_distance_km)} / {fmtShoe(shoe.retirement_threshold_km)}
                    </div>
                    <div className="flex items-center justify-end gap-2 mt-1">
                      <button
                        onClick={() => startEdit(shoe)}
                        className="text-xs text-gray-400 hover:text-blue-600"
                      >
                        Edit
                      </button>
                      <span className="text-gray-200">·</span>
                      <button
                        onClick={() => retireMutation.mutate(shoe.id)}
                        className="text-xs text-gray-400 hover:text-red-500"
                      >
                        Retire
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {active.length === 0 && !showForm && (
        <div className="text-center text-gray-400 text-sm py-12">
          No shoes yet. Add your first pair!
        </div>
      )}

      {retired.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Retired</h2>
          <div className="bg-white border border-gray-200 rounded-xl shadow-sm divide-y divide-gray-50 opacity-60">
            {retired.map((shoe) => (
              <div
                key={shoe.id}
                className="p-4 flex items-center justify-between gap-3"
              >
                {editingId === shoe.id ? (
                  renderEditor(shoe.id)
                ) : (
                  <>
                    <Link
                      to={`/activities?shoe=${shoe.id}`}
                      className="min-w-0 hover:opacity-80 transition-opacity"
                    >
                      <div className="font-medium text-gray-600">{shoe.name}</div>
                      {shoe.brand && <div className="text-xs text-gray-400">{shoe.brand}</div>}
                    </Link>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <span className="text-sm font-mono text-gray-500">
                        {fmtShoe(shoe.total_distance_km)}
                      </span>
                      <button
                        onClick={() => startEdit(shoe)}
                        className="text-xs text-gray-400 hover:text-blue-600"
                      >
                        Edit
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
