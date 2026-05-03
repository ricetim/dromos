import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getPlan, getPlanWorkouts } from "../api/client";
import { useUnits } from "../contexts/UnitsContext";
import { formatDateShort } from "../utils/dates";

interface Workout {
  id: number;
  scheduled_date: string;
  week_number: number;
  workout_type: string;
  description: string;
  target_distance_m: number | null;
  target_pace_s_per_km: number | null;
  completed_activity_id: number | null;
  optional: boolean;
  status: string;
}

interface Plan {
  id: number;
  name: string;
  source: string;
  goal_distance: string;
  goal_race_date: string;
  start_date: string;
  target_vdot: number | null;
  peak_weekly_km: number | null;
}

const TYPE_COLORS: Record<string, string> = {
  easy:          "bg-green-50  text-green-800  border-green-200",
  recovery:      "bg-green-50  text-green-600  border-green-100",
  long:          "bg-blue-50   text-blue-800   border-blue-200",
  marathon_pace: "bg-purple-50 text-purple-800 border-purple-200",
  threshold:     "bg-yellow-50 text-yellow-800 border-yellow-200",
  interval:      "bg-orange-50 text-orange-800 border-orange-200",
  repetition:    "bg-red-50    text-red-800    border-red-200",
  rest:          "bg-gray-50   text-gray-400   border-gray-100",
};

const TYPE_LABEL: Record<string, string> = {
  easy:          "E",
  long:          "L",
  marathon_pace: "MP",
  threshold:     "T",
  interval:      "I",
  repetition:    "R",
  rest:          "—",
};

const STATUS_RING: Record<string, string> = {
  completed: "ring-2 ring-green-400",
  missed:    "ring-2 ring-red-300",
  today:     "ring-2 ring-blue-500",
};

function WorkoutRow({ w, fmtPace, fmtDist }: {
  w: Workout;
  fmtPace: (s: number | null) => string;
  fmtDist: (m: number) => string;
}) {
  const colorClass = TYPE_COLORS[w.workout_type] ?? "bg-gray-100 text-gray-600 border-gray-200";
  const ringClass  = STATUS_RING[w.status] ?? "";
  const typeLabel  = TYPE_LABEL[w.workout_type] ?? w.workout_type;
  const dayLabel = formatDateShort(w.scheduled_date + "T12:00:00");
  const isQ = w.description.startsWith("Q");

  return (
    <div className={`border rounded-lg p-3 ${colorClass} ${ringClass} ${w.optional ? "opacity-60 border-dashed" : ""} relative`}>
      {/* Header row */}
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-gray-400">{dayLabel}</span>
          {w.optional && (
            <span className="text-[9px] px-1 py-0.5 bg-gray-200 text-gray-500 rounded">optional</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {w.target_distance_m != null && w.workout_type !== "rest" && (
            <span className="text-xs text-gray-500">{fmtDist(w.target_distance_m)}</span>
          )}
          <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${colorClass}`}>{typeLabel}</span>
        </div>
      </div>

      {/* Description */}
      {w.workout_type !== "rest" && (
        <div className={`text-xs leading-snug ${isQ ? "font-medium" : "text-gray-500"}`}>
          {w.description}
        </div>
      )}

      {/* Pace */}
      {w.target_pace_s_per_km != null && (
        <div className="text-[10px] font-mono mt-1 opacity-70">
          @ {fmtPace(w.target_pace_s_per_km)}
        </div>
      )}

      {/* Completed dot */}
      {w.completed_activity_id && (
        <Link
          to={`/activities/${w.completed_activity_id}`}
          className="absolute top-2 right-2 w-2 h-2 bg-green-500 rounded-full"
          title="View completed activity"
        />
      )}
    </div>
  );
}

export default function PlanDetail() {
  const { id } = useParams<{ id: string }>();
  const planId = parseInt(id ?? "0");
  const { fmtDist, fmtPace } = useUnits();

  const { data: plan } = useQuery<Plan>({
    queryKey: ["plan", planId],
    queryFn: () => getPlan(planId),
  });

  const { data: workouts = [], isLoading } = useQuery<Workout[]>({
    queryKey: ["plan-workouts", planId],
    queryFn: () => getPlanWorkouts(planId),
  });

  if (isLoading || !plan) {
    return <div className="p-8 text-center text-gray-400">Loading plan…</div>;
  }

  const weeks: Record<number, Workout[]> = {};
  for (const w of workouts) {
    if (!weeks[w.week_number]) weeks[w.week_number] = [];
    weeks[w.week_number].push(w);
  }

  const completedCount  = workouts.filter((w) => w.status === "completed").length;
  const totalWorkouts   = workouts.filter((w) => w.workout_type !== "rest" && !w.optional).length;

  const sourceLabel = plan.source.startsWith("daniels")
    ? plan.source === "daniels"
      ? "Daniels Marathon"
      : `Daniels ${plan.source.split("_")[1].charAt(0).toUpperCase() + plan.source.split("_")[1].slice(1)}`
    : "Pfitzinger";

  return (
    <div className="p-4 max-w-5xl mx-auto space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <Link to="/plans" className="text-xs text-blue-600 hover:underline">← Plans</Link>
          <h1 className="text-xl font-bold text-gray-800 mt-1">{plan.name}</h1>
          <div className="text-sm text-gray-500 mt-0.5">
            {sourceLabel}
            {plan.goal_distance && plan.source === "daniels" && ` · ${plan.goal_distance.toUpperCase()}`}
            {plan.target_vdot && ` · VDOT ${plan.target_vdot}`}
            {" · ends "}
            {formatDateShort(plan.goal_race_date + "T12:00:00")}
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-blue-600">{completedCount}/{totalWorkouts}</div>
          <div className="text-xs text-gray-400">workouts done</div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-2 text-xs">
        {(Object.entries(TYPE_LABEL) as [string, string][])
          .filter(([k]) => k !== "rest" && k !== "recovery")
          .map(([type, label]) => (
            <span key={type} className={`px-2 py-0.5 rounded border ${TYPE_COLORS[type]}`}>
              {label} — {type === "easy" ? "Easy" : type === "long" ? "Long" : type === "marathon_pace" ? "Marathon" : type.charAt(0).toUpperCase() + type.slice(1)}
            </span>
          ))}
        <span className="px-2 py-0.5 rounded border border-dashed border-gray-300 text-gray-400">
          optional
        </span>
      </div>

      {/* Week grid */}
      <div className="space-y-4">
        {Object.entries(weeks).map(([weekNum, days]) => {
          const weekDist = days.reduce((s, w) => s + (w.target_distance_m ?? 0), 0);
          return (
            <div key={weekNum}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold text-gray-500">Week {weekNum}</span>
                <span className="text-xs text-gray-400">{fmtDist(weekDist)} total</span>
              </div>
              <div className="grid grid-cols-7 gap-1">
                {days.map((w) => (
                  <WorkoutRow key={w.id} w={w} fmtPace={fmtPace} fmtDist={fmtDist} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
