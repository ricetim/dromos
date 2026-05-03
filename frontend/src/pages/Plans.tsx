import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getPlans, createPlan, deletePlan, getVdot } from "../api/client";
import { formatDateShort } from "../utils/dates";

interface Plan {
  id: number;
  name: string;
  source: string;
  goal_distance: string;
  goal_race_date: string;
  start_date: string;
  target_vdot: number | null;
  peak_weekly_km: number | null;
  notes: string | null;
}

const SOURCES = [
  { value: "daniels",       label: "Daniels — Full Marathon Plan" },
  { value: "daniels_white", label: "Daniels — White (Foundation, 4 wks)" },
  { value: "daniels_red",   label: "Daniels — Red (Early Quality, 4 wks)" },
  { value: "daniels_blue",  label: "Daniels — Blue (Intervals, 4 wks)" },
  { value: "daniels_gold",  label: "Daniels — Gold (Peak Quality, 4 wks)" },
  { value: "pfitzinger",    label: "Pfitzinger 18/55" },
];

const PHASE_SOURCES = new Set(["daniels_white", "daniels_red", "daniels_blue", "daniels_gold"]);

const DISTANCES = ["5k", "10k", "half", "marathon"];

export default function Plans() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    source: "daniels",
    goal_distance: "marathon",
    goal_race_date: "",
    start_date: "",
    target_vdot: "",
    peak_weekly_km: "88",
    name: "",
    notes: "",
  });

  const { data: plans = [] } = useQuery<Plan[]>({
    queryKey: ["plans"],
    queryFn: getPlans,
  });

  const { data: vdotData } = useQuery({
    queryKey: ["vdot"],
    queryFn: getVdot,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const isPhase = PHASE_SOURCES.has(form.source);
      const payload: Record<string, unknown> = {
        source: form.source,
        name: form.name || undefined,
        notes: form.notes || undefined,
      };
      if (isPhase) {
        payload.target_vdot = parseFloat(form.target_vdot);
        if (form.start_date) payload.start_date = form.start_date;
      } else if (form.source === "daniels") {
        payload.goal_distance = form.goal_distance;
        payload.goal_race_date = form.goal_race_date;
        payload.target_vdot = parseFloat(form.target_vdot);
      } else {
        payload.goal_distance = form.goal_distance;
        payload.goal_race_date = form.goal_race_date;
        payload.peak_weekly_km = parseFloat(form.peak_weekly_km);
      }
      return createPlan(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      setShowForm(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deletePlan,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plans"] }),
  });

  const suggestedVdot = vdotData?.vdot?.toFixed(1) ?? "";

  return (
    <div className="p-4 max-w-3xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-800">Training Plans</h1>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          + New Plan
        </button>
      </div>

      {showForm && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-4">
          <h2 className="text-sm font-semibold text-gray-700">Generate Training Plan</h2>
          {(() => {
            const isPhase = PHASE_SOURCES.has(form.source);
            return (
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="block text-xs text-gray-500 mb-1">Plan source</label>
                <select
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                  value={form.source}
                  onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}
                >
                  {SOURCES.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>

              {/* Phase plans: only VDOT + optional start date */}
              {isPhase ? (
                <>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">
                      Target VDOT{suggestedVdot && ` (current: ${suggestedVdot})`}
                    </label>
                    <input
                      type="number" step="0.1"
                      className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                      value={form.target_vdot}
                      onChange={(e) => setForm((f) => ({ ...f, target_vdot: e.target.value }))}
                      placeholder={suggestedVdot || "e.g. 42.0"}
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Start date (optional, defaults to next Monday)</label>
                    <input
                      type="date"
                      className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                      value={form.start_date}
                      onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))}
                    />
                  </div>
                </>
              ) : (
                <>
                  {form.source !== "daniels" || true ? (
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Goal distance</label>
                      <select
                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                        value={form.goal_distance}
                        onChange={(e) => setForm((f) => ({ ...f, goal_distance: e.target.value }))}
                      >
                        {DISTANCES.map((d) => <option key={d} value={d}>{d}</option>)}
                      </select>
                    </div>
                  ) : null}
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Race date</label>
                    <input
                      type="date"
                      className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                      value={form.goal_race_date}
                      onChange={(e) => setForm((f) => ({ ...f, goal_race_date: e.target.value }))}
                    />
                  </div>
                  {form.source === "daniels" ? (
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">
                        Target VDOT{suggestedVdot && ` (current: ${suggestedVdot})`}
                      </label>
                      <input
                        type="number" step="0.1"
                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                        value={form.target_vdot}
                        onChange={(e) => setForm((f) => ({ ...f, target_vdot: e.target.value }))}
                        placeholder={suggestedVdot || "e.g. 50.0"}
                      />
                    </div>
                  ) : (
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Peak weekly km</label>
                      <input
                        type="number"
                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                        value={form.peak_weekly_km}
                        onChange={(e) => setForm((f) => ({ ...f, peak_weekly_km: e.target.value }))}
                      />
                    </div>
                  )}
                </>
              )}

              <div>
                <label className="block text-xs text-gray-500 mb-1">Plan name (optional)</label>
                <input
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Auto-generated if blank"
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
            </div>
            );
          })()}
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => setShowForm(false)}
              className="px-3 py-1.5 text-sm text-gray-600 border border-gray-300 rounded"
            >
              Cancel
            </button>
            <button
              onClick={() => createMutation.mutate()}
              disabled={(!PHASE_SOURCES.has(form.source) && !form.goal_race_date) || !form.target_vdot && form.source !== "pfitzinger" || createMutation.isPending}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
            >
              {createMutation.isPending ? "Generating…" : "Generate"}
            </button>
          </div>
          {createMutation.isError && (
            <div className="text-xs text-red-500">Failed to create plan. Check your inputs.</div>
          )}
        </div>
      )}

      {plans.length === 0 && !showForm ? (
        <div className="text-center text-gray-400 text-sm py-12">
          No training plans yet. Generate your first plan!
        </div>
      ) : (
        <div className="space-y-3">
          {plans.map((plan) => (
            <div key={plan.id} className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
              <div className="flex items-start justify-between">
                <div>
                  <Link
                    to={`/plans/${plan.id}`}
                    className="font-medium text-blue-600 hover:underline"
                  >
                    {plan.name}
                  </Link>
                  <div className="text-xs text-gray-400 mt-0.5">
                    {plan.source === "daniels" ? "Daniels" : "Pfitzinger"} ·{" "}
                    {plan.goal_distance.toUpperCase()} · Race:{" "}
                    {formatDateShort(plan.goal_race_date + "T12:00:00")}
                  </div>
                  {plan.target_vdot && (
                    <div className="text-xs text-gray-400">VDOT {plan.target_vdot}</div>
                  )}
                  {plan.peak_weekly_km && (
                    <div className="text-xs text-gray-400">{plan.peak_weekly_km} km/wk peak</div>
                  )}
                </div>
                <div className="flex gap-2 items-center">
                  <Link
                    to={`/plans/${plan.id}`}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    View →
                  </Link>
                  <button
                    onClick={() => deleteMutation.mutate(plan.id)}
                    className="text-xs text-gray-400 hover:text-red-500"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
