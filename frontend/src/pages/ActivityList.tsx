import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { getActivities, uploadFit, getActivityFull, getDataPoints, getShoes } from "../api/client";
import { Activity } from "../types";
import { useUnits } from "../contexts/UnitsContext";
import RouteThumbnail from "../components/RouteThumbnail";
import RpeBadge from "../components/RpeBadge";
import { PaceFraction } from "../components/PaceFraction";
import { formatDate } from "../utils/dates";
import { PAGE_SIZE } from "../config";

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatWorkoutName(sportType: string, name?: string | null): string {
  if (name) return name;
  return sportType
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

type QuickFilter = "all" | "hard" | "easy" | "race" | "long";

const QUICK_FILTERS: { key: QuickFilter; label: string }[] = [
  { key: "all",  label: "All" },
  { key: "hard", label: "Hard Effort" },
  { key: "easy", label: "Easy" },
  { key: "race", label: "Race" },
  { key: "long", label: "Long Run" },
];

function matchesFilter(a: Activity, filter: QuickFilter): boolean {
  switch (filter) {
    case "all":  return true;
    case "hard": return a.rpe != null && a.rpe >= 4;
    case "easy": return a.rpe != null && a.rpe <= 2;
    case "race": {
      const haystack = [a.name, a.notes].join(" ").toLowerCase();
      return haystack.includes("race") || haystack.includes("5k") || haystack.includes("10k") ||
             haystack.includes("half marathon") || haystack.includes("marathon");
    }
    case "long": {
      // 15 km / ~9.3 mi threshold for "long"
      return a.distance_m >= 15000;
    }
  }
}

function matchesSearch(a: Activity, q: string): boolean {
  if (!q) return true;
  const lower = q.toLowerCase();
  return (
    (a.name ?? "").toLowerCase().includes(lower) ||
    (a.notes ?? "").toLowerCase().includes(lower) ||
    a.sport_type.toLowerCase().includes(lower)
  );
}

export default function ActivityList() {
  const qc = useQueryClient();
  const { fmtDist } = useUnits();
  const [search, setSearch] = useState("");
  const [quickFilter, setQuickFilter] = useState<QuickFilter>("all");
  const [page, setPage] = useState(1);
  const [searchParams, setSearchParams] = useSearchParams();
  const shoeIdParam = searchParams.get("shoe");
  const shoeId = shoeIdParam ? parseInt(shoeIdParam, 10) : null;

  const { data: activities = [], isLoading } = useQuery<Activity[]>({
    queryKey: ["activities"],
    queryFn: getActivities,
  });

  // Load shoes only when filtering by shoe
  const { data: shoes = [] } = useQuery<{ id: number; name: string; activity_ids?: number[] }[]>({
    queryKey: ["shoes"],
    queryFn: getShoes,
    enabled: shoeId !== null,
    staleTime: 60_000,
  });
  const activeShoe = shoeId !== null ? shoes.find((s) => s.id === shoeId) : null;
  const shoeActivityIds = activeShoe?.activity_ids ? new Set(activeShoe.activity_ids) : null;

  const upload = useMutation({
    mutationFn: uploadFit,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["activities"] });
      qc.invalidateQueries({ queryKey: ["stats-summary"] });
      qc.invalidateQueries({ queryKey: ["personal-bests"] });
      qc.invalidateQueries({ queryKey: ["vdot"] });
    },
  });

  // Filter + search
  const filtered = activities.filter(
    (a) =>
      matchesFilter(a, quickFilter) &&
      matchesSearch(a, search) &&
      (shoeActivityIds === null || shoeActivityIds.has(a.id))
  );

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const clampedPage = Math.min(page, totalPages);
  const pageStart = (clampedPage - 1) * PAGE_SIZE;
  const pageItems = filtered.slice(pageStart, pageStart + PAGE_SIZE);

  function handleSearchChange(val: string) {
    setSearch(val);
    setPage(1);
  }

  function handleFilterChange(f: QuickFilter) {
    setQuickFilter(f);
    setPage(1);
  }

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Activities</h1>
        <label className="cursor-pointer bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium">
          {upload.isPending ? "Uploading…" : "Upload .fit"}
          <input
            type="file"
            accept=".fit"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload.mutate(f);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      {upload.isError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          Upload failed — make sure the file is a valid .fit file.
        </div>
      )}

      {/* Shoe filter banner */}
      {activeShoe && (
        <div className="mb-4 flex items-center gap-2 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-700">
          <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M3 4a1 1 0 011-1h1.586A1 1 0 016.293 3.293L9 6h7a1 1 0 01.894 1.447l-3 6A1 1 0 0113 14H6a1 1 0 01-.894-.553L2.106 7.447A1 1 0 013 6h.001V4z" clipRule="evenodd" />
          </svg>
          <span>Showing runs in <strong>{activeShoe.name}</strong></span>
          <button
            onClick={() => setSearchParams({})}
            className="ml-auto text-blue-400 hover:text-blue-700"
            aria-label="Clear shoe filter"
          >
            ✕
          </button>
        </div>
      )}

      {/* Search + quick filters */}
      {!isLoading && activities.length > 0 && (
        <div className="mb-4 space-y-2">
          <input
            type="text"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search activities…"
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
          />
          <div className="flex gap-2 flex-wrap">
            {QUICK_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => handleFilterChange(f.key)}
                className={`px-3 py-1 text-xs rounded-full border font-medium transition-colors ${
                  quickFilter === f.key
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
                }`}
              >
                {f.label}
              </button>
            ))}
            {(search || quickFilter !== "all") && (
              <button
                onClick={() => { setSearch(""); setQuickFilter("all"); setPage(1); }}
                className="px-3 py-1 text-xs rounded-full border text-gray-400 border-gray-200 hover:border-gray-400 transition-colors"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}

      {isLoading && <p className="text-gray-500">Loading…</p>}

      {!isLoading && activities.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg">No activities yet.</p>
          <p className="text-sm mt-1">Upload a .fit file to get started.</p>
        </div>
      )}

      {!isLoading && activities.length > 0 && filtered.length === 0 && (
        <div className="text-center py-12 text-gray-400">
          <p className="text-base">No activities match your search.</p>
          <button
            onClick={() => { setSearch(""); setQuickFilter("all"); setPage(1); }}
            className="mt-2 text-sm text-blue-500 hover:underline"
          >
            Clear filters
          </button>
        </div>
      )}

      <ul className="space-y-3">
        {pageItems.map((a) => (
          <li key={a.id}>
            <Link
              to={`/activities/${a.id}`}
              className="flex items-center gap-4 p-3 bg-white rounded-xl border border-gray-200 hover:border-blue-400 hover:shadow-sm transition-all"
              onMouseEnter={() => {
                qc.prefetchQuery({ queryKey: ["activity-full", a.id], queryFn: () => getActivityFull(a.id), staleTime: Infinity });
                qc.prefetchQuery({ queryKey: ["datapoints", a.id], queryFn: () => getDataPoints(a.id), staleTime: Infinity });
              }}
            >
              {/* Route thumbnail */}
              <RouteThumbnail track={a.track} width={112} height={84} />

              {/* Main info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-xs text-gray-400">{formatDate(a.started_at)}</span>
                  {a.rpe != null && a.rpe > 0 && <RpeBadge rpe={a.rpe} />}
                </div>
                <div className="text-base font-semibold text-gray-900 mb-0.5">
                  {formatWorkoutName(a.sport_type, a.name)}
                </div>
                {a.notes && (
                  <p className="text-xs text-gray-400 truncate leading-relaxed">
                    {a.notes.length > 120 ? a.notes.slice(0, 120) + "…" : a.notes}
                  </p>
                )}
              </div>

              {/* Stats */}
              <div className="flex gap-4 text-sm text-right flex-shrink-0">
                <div>
                  <div className="font-semibold text-gray-900">{fmtDist(a.distance_m)}</div>
                  <div className="text-xs text-gray-400">dist</div>
                </div>
                <div>
                  <div className="font-semibold text-gray-900">{formatDuration(a.duration_s)}</div>
                  <div className="text-xs text-gray-400">time</div>
                </div>
                <div>
                  <PaceFraction sPerKm={a.avg_pace_s_per_km} className="font-semibold text-gray-900" />
                  <div className="text-xs text-gray-400">pace</div>
                </div>
                {a.avg_hr && (
                  <div>
                    <div className="font-semibold text-gray-900">{a.avg_hr}</div>
                    <div className="text-xs text-gray-400">bpm</div>
                  </div>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>

      {/* Pagination */}
      {!isLoading && totalPages > 1 && (
        <div className="mt-6 flex items-center justify-between text-sm">
          <span className="text-gray-400">
            {pageStart + 1}–{Math.min(pageStart + PAGE_SIZE, filtered.length)} of {filtered.length}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={clampedPage === 1}
              className="px-3 py-1.5 rounded border border-gray-300 text-gray-600 hover:border-blue-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              ← Prev
            </button>
            <span className="px-3 py-1.5 text-gray-500">
              {clampedPage} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={clampedPage === totalPages}
              className="px-3 py-1.5 rounded border border-gray-300 text-gray-600 hover:border-blue-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
