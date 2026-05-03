import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getShoes, createShoe, updateShoe } from "../api/client";
import { useUnits } from "../contexts/UnitsContext";
import { SHOE_RETIREMENT_MI, SHOE_RETIREMENT_KM } from "../config";

interface Shoe {
  id: number;
  name: string;
  brand: string | null;
  retired: boolean;
  notes: string | null;
  retirement_threshold_km: number;
  total_distance_km: number;
  activity_ids?: number[];
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
      setForm({ name: "", brand: "", retirement_threshold: defaultThreshold });
      setShowForm(false);
    },
  });

  const retireMutation = useMutation({
    mutationFn: (id: number) => updateShoe(id, { retired: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shoes"] }),
  });

  const active = shoes.filter((s) => !s.retired);
  const retired = shoes.filter((s) => s.retired);

  return (
    <div className="p-4 max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-xl font-bold text-gray-800">Gear</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowForm((v) => !v)}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            + Add Shoe
          </button>
        </div>
      </div>

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
                <button
                  onClick={() => retireMutation.mutate(shoe.id)}
                  className="text-xs text-gray-400 hover:text-red-500 mt-1"
                >
                  Retire
                </button>
              </div>
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
              <Link
                key={shoe.id}
                to={`/activities?shoe=${shoe.id}`}
                className="p-4 flex items-center justify-between hover:opacity-80 transition-opacity"
              >
                <div>
                  <div className="font-medium text-gray-600">{shoe.name}</div>
                  {shoe.brand && <div className="text-xs text-gray-400">{shoe.brand}</div>}
                </div>
                <div className="text-sm font-mono text-gray-500">
                  {fmtShoe(shoe.total_distance_km)}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
