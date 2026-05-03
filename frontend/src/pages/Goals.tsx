import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getGoals, createGoal, updateGoal, deleteGoal } from "../api/client";
import { useUnits } from "../contexts/UnitsContext";
import { formatDateShortNoYear } from "../utils/dates";
import { KM_PER_MI } from "../config";

interface Goal {
  id: number;
  type: string;
  target_value: number;
  period_start: string;
  period_end: string;
  notes: string | null;
}

interface GoalWithProgress {
  goal: Goal;
  progress_km: number;
}

const GOAL_TYPES = [
  { value: "weekly_distance", label: "Weekly Distance" },
  { value: "monthly_distance", label: "Monthly Distance" },
  { value: "annual_distance", label: "Annual Distance" },
];

function ProgressBar({ pct }: { pct: number }) {
  const clamped = Math.min(pct, 100);
  const color = pct >= 100 ? "bg-green-500" : pct >= 70 ? "bg-blue-500" : "bg-blue-400";
  return (
    <div className="w-full bg-gray-100 rounded-full h-2.5 mt-2">
      <div
        className={`${color} h-2.5 rounded-full transition-all`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

function getDefaultDates(type: string): { period_start: string; period_end: string } {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  if (type === "annual_distance") {
    return { period_start: `${y}-01-01`, period_end: `${y}-12-31` };
  }
  if (type === "monthly_distance") {
    const firstOfMonth = new Date(y, m, 1);
    const lastOfMonth  = new Date(y, m + 1, 0);
    return {
      period_start: firstOfMonth.toISOString().slice(0, 10),
      period_end:   lastOfMonth.toISOString().slice(0, 10),
    };
  }
  // weekly
  const day = now.getDay();
  const monday = new Date(now);
  monday.setDate(now.getDate() - ((day + 6) % 7));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return {
    period_start: monday.toISOString().slice(0, 10),
    period_end:   sunday.toISOString().slice(0, 10),
  };
}

function GoalCard({
  item,
  onDelete,
  onSave,
}: {
  item: GoalWithProgress;
  onDelete: () => void;
  onSave: (id: number, data: object) => void;
}) {
  const { system } = useUnits();
  const { goal, progress_km } = item;
  const [editing, setEditing] = useState(false);

  const fmtGoalDist = (km: number) =>
    system === "imperial"
      ? (km / KM_PER_MI).toFixed(1) + " mi"
      : km.toFixed(1) + " km";

  const defaultTarget =
    system === "imperial"
      ? (goal.target_value / KM_PER_MI).toFixed(1)
      : goal.target_value.toFixed(1);

  const [editForm, setEditForm] = useState({
    type: goal.type,
    target_value: defaultTarget,
    period_start: goal.period_start,
    period_end: goal.period_end,
    notes: goal.notes ?? "",
  });

  const pct = (progress_km / goal.target_value) * 100;
  const typeLabel = GOAL_TYPES.find((t) => t.value === goal.type)?.label ?? goal.type;
  const start = formatDateShortNoYear(goal.period_start + "T12:00:00");
  const end   = formatDateShortNoYear(goal.period_end + "T12:00:00");

  const now       = Date.now();
  const startMs   = new Date(goal.period_start).getTime();
  const endMs     = new Date(goal.period_end).getTime();
  const totalDays = (endMs - startMs) || 1;
  const elapsed   = Math.max(0, Math.min(now - startMs, totalDays));
  const expectedPct = elapsed / totalDays;
  const actualPct   = progress_km / goal.target_value;
  const done = now >= endMs;
  const onTrack = actualPct >= expectedPct;

  const trackLabel = done
    ? pct >= 100 ? "Goal achieved!" : "Goal not reached"
    : onTrack
      ? `On track · ${((actualPct - expectedPct) * 100).toFixed(0)}% ahead`
      : `Behind pace · ${system === "imperial"
        ? ((expectedPct - actualPct) * goal.target_value / KM_PER_MI).toFixed(1) + " mi"
        : ((expectedPct - actualPct) * goal.target_value).toFixed(1) + " km"} short`;
  const trackColor = done
    ? pct >= 100 ? "text-green-600" : "text-red-500"
    : onTrack ? "text-green-600" : "text-orange-500";

  // Projection: extrapolate current pace to end of period
  let projectionText: string | null = null;
  if (!done && elapsed > 0 && actualPct > 0) {
    const projectedKm = progress_km / (elapsed / totalDays);
    const diff = projectedKm - goal.target_value;
    const diffFmt = fmtGoalDist(Math.abs(diff));
    projectionText = diff >= 0
      ? `On pace for ${fmtGoalDist(projectedKm)} (+${diffFmt} over goal)`
      : `On pace for ${fmtGoalDist(projectedKm)} (${diffFmt} short of goal)`;
  }

  function handleSave() {
    const targetKm = system === "imperial"
      ? parseFloat(editForm.target_value) * KM_PER_MI
      : parseFloat(editForm.target_value);
    onSave(goal.id, {
      type: editForm.type,
      target_value: targetKm,
      period_start: editForm.period_start,
      period_end: editForm.period_end,
      notes: editForm.notes || null,
    });
    setEditing(false);
  }

  if (editing) {
    return (
      <div className="bg-white border border-blue-300 rounded-xl p-4 shadow-sm space-y-3">
        <h3 className="text-sm font-semibold text-gray-700">Edit Goal</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-xs text-gray-500 mb-1">Type</label>
            <select
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
              value={editForm.type}
              onChange={(e) => {
                const newType = e.target.value;
                setEditForm((f) => ({ ...f, type: newType, ...getDefaultDates(newType) }));
              }}
            >
              {GOAL_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Target ({system === "imperial" ? "mi" : "km"})
            </label>
            <input
              type="number"
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
              value={editForm.target_value}
              onChange={(e) => setEditForm((f) => ({ ...f, target_value: e.target.value }))}
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Notes</label>
            <input
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
              value={editForm.notes}
              onChange={(e) => setEditForm((f) => ({ ...f, notes: e.target.value }))}
              placeholder="Optional"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Start date</label>
            <input
              type="date"
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
              value={editForm.period_start}
              onChange={(e) => setEditForm((f) => ({ ...f, period_start: e.target.value }))}
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">End date</label>
            <input
              type="date"
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
              value={editForm.period_end}
              onChange={(e) => setEditForm((f) => ({ ...f, period_end: e.target.value }))}
            />
          </div>
        </div>
        <div className="flex gap-2 justify-end">
          <button
            onClick={() => setEditing(false)}
            className="px-3 py-1.5 text-sm text-gray-600 border border-gray-300 rounded"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!editForm.target_value}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-medium text-gray-800">{typeLabel}</div>
          <div className="text-xs text-gray-400 mt-0.5">{start} – {end}</div>
          {goal.notes && <div className="text-xs text-gray-500 mt-1">{goal.notes}</div>}
        </div>
        <div className="text-right">
          <div className={`text-lg font-bold ${pct >= 100 ? "text-green-600" : "text-blue-600"}`}>
            {fmtGoalDist(progress_km)}
          </div>
          <div className="text-xs text-gray-400">of {fmtGoalDist(goal.target_value)}</div>
        </div>
      </div>
      <ProgressBar pct={pct} />
      <div className="flex items-center justify-between mt-2">
        <div className={`text-xs font-medium ${trackColor}`}>{trackLabel}</div>
        <div className="flex gap-3">
          <button
            onClick={() => setEditing(true)}
            className="text-xs text-gray-400 hover:text-blue-500"
          >
            Edit
          </button>
          <button
            onClick={onDelete}
            className="text-xs text-gray-400 hover:text-red-500"
          >
            Delete
          </button>
        </div>
      </div>
      {projectionText && (
        <div className="mt-2 text-xs text-gray-400 italic">{projectionText}</div>
      )}
    </div>
  );
}

export default function Goals() {
  const qc = useQueryClient();
  const { system } = useUnits();
  const [showForm, setShowForm] = useState(false);

  const defaultTarget = system === "imperial" ? "62" : "100";
  const [form, setForm] = useState(() => {
    const defaultType = "monthly_distance";
    const { period_start, period_end } = getDefaultDates(defaultType);
    return {
      type: defaultType,
      target_value: defaultTarget,
      period_start,
      period_end,
      notes: "",
    };
  });

  const { data: goals = [] } = useQuery<GoalWithProgress[]>({
    queryKey: ["goals"],
    queryFn: getGoals,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const targetKm = system === "imperial"
        ? parseFloat(form.target_value) * KM_PER_MI
        : parseFloat(form.target_value);
      return createGoal({
        type: form.type,
        target_value: targetKm,
        period_start: form.period_start,
        period_end: form.period_end,
        notes: form.notes || null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["goals"] });
      setShowForm(false);
    },
    onError: () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => updateGoal(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
    onError:   () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteGoal,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
    onError:   () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });

  return (
    <div className="p-4 max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-800">Goals</h1>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          + New Goal
        </button>
      </div>

      {showForm && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3">
          <h2 className="text-sm font-semibold text-gray-700">New Goal</h2>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="block text-xs text-gray-500 mb-1">Type</label>
              <select
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                value={form.type}
                onChange={(e) => {
                  const newType = e.target.value;
                  setForm((f) => ({ ...f, type: newType, ...getDefaultDates(newType) }));
                }}
              >
                {GOAL_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">
                Target ({system === "imperial" ? "mi" : "km"})
              </label>
              <input
                type="number"
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                value={form.target_value}
                onChange={(e) => setForm((f) => ({ ...f, target_value: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Notes</label>
              <input
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                placeholder="Optional"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Start date</label>
              <input
                type="date"
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                value={form.period_start}
                onChange={(e) => setForm((f) => ({ ...f, period_start: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">End date</label>
              <input
                type="date"
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                value={form.period_end}
                onChange={(e) => setForm((f) => ({ ...f, period_end: e.target.value }))}
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
              disabled={!form.target_value || createMutation.isPending}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
            >
              Save
            </button>
          </div>
        </div>
      )}

      {goals.length === 0 && !showForm ? (
        <div className="text-center text-gray-400 text-sm py-12">
          No goals yet. Set your first distance goal!
        </div>
      ) : (
        <div className="space-y-3">
          {goals.map((item) => (
            <GoalCard
              key={item.goal.id}
              item={item}
              onDelete={() => deleteMutation.mutate(item.goal.id)}
              onSave={(id, data) => updateMutation.mutate({ id, data })}
            />
          ))}
        </div>
      )}
    </div>
  );
}
