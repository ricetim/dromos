import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getActivities } from "../api/client";
import { useUnits } from "../contexts/UnitsContext";
import type { Activity } from "../types";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const SPORT_COLORS: Record<string, string> = {
  run:          "bg-blue-100 text-blue-800 border-blue-200",
  trail_run:    "bg-green-100 text-green-800 border-green-200",
  cycling:      "bg-yellow-100 text-yellow-800 border-yellow-200",
  swimming:     "bg-cyan-100 text-cyan-800 border-cyan-200",
  walking:      "bg-gray-100 text-gray-700 border-gray-200",
};

function sportColor(sport: string): string {
  return SPORT_COLORS[sport] ?? "bg-purple-100 text-purple-800 border-purple-200";
}

function formatActivityName(act: Activity): string {
  if (act.name) return act.name;
  return act.sport_type.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

/** Return the Sunday of the week containing `d`. */
function weekSunday(d: Date): Date {
  const result = new Date(d);
  const dow = result.getDay(); // 0=Sun already
  result.setDate(result.getDate() - dow);
  result.setHours(0, 0, 0, 0);
  return result;
}

/** Local YYYY-MM-DD string (not UTC) */
function localDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Build a 5-or-6 row calendar grid for the given year/month.
 *  Returns an array of weeks, each week is 7 Date objects. */
function buildCalendarGrid(year: number, month: number): Date[][] {
  const firstDay = new Date(year, month, 1);
  const lastDay  = new Date(year, month + 1, 0);
  const start    = weekSunday(firstDay);
  const weeks: Date[][] = [];
  let current = new Date(start);
  while (current <= lastDay || weeks.length < 4) {
    const week: Date[] = [];
    for (let i = 0; i < 7; i++) {
      week.push(new Date(current));
      current.setDate(current.getDate() + 1);
    }
    weeks.push(week);
    if (current > lastDay && weeks.length >= 4) break;
  }
  return weeks;
}

export default function CalendarView() {
  const today = new Date();
  const todayKey = localDateKey(today);
  const [year, setYear]   = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());
  const { fmtDist } = useUnits();

  const { data: activities = [] } = useQuery<Activity[]>({
    queryKey: ["activities"],
    queryFn: getActivities,
  });

  // Index activities by local YYYY-MM-DD
  const byDate: Record<string, Activity[]> = {};
  for (const act of activities) {
    // Parse as local time to avoid UTC-offset day shift
    const local = new Date(act.started_at);
    const key = localDateKey(local);
    if (!byDate[key]) byDate[key] = [];
    byDate[key].push(act);
  }

  const weeks = buildCalendarGrid(year, month);
  const monthLabel = new Date(year, month, 1).toLocaleString("en-US", {
    month: "long", year: "numeric", timeZone: "America/Los_Angeles",
  });

  // Monthly summary: all activities whose started_at falls in this year/month
  const monthActs = activities.filter((a) => {
    const d = new Date(a.started_at);
    return d.getFullYear() === year && d.getMonth() === month;
  });
  const monthDistM = monthActs.reduce((s, a) => s + (a.distance_m ?? 0), 0);
  const monthRuns  = monthActs.length;

  // Key of the Monday of the week containing today (for row highlight)
  const todayWeekMonday = localDateKey(weekSunday(today));

  function prevMonth() {
    if (month === 0) { setYear(y => y - 1); setMonth(11); }
    else setMonth(m => m - 1);
  }
  function nextMonth() {
    if (month === 11) { setYear(y => y + 1); setMonth(0); }
    else setMonth(m => m + 1);
  }

  return (
    <div className="p-4 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-xl font-bold text-gray-800">Calendar</h1>
        <div className="flex items-center gap-3">
          <button
            onClick={prevMonth}
            className="px-2 py-1 text-sm text-gray-500 hover:text-gray-800 border border-gray-300 rounded"
          >
            ‹
          </button>
          <span className="text-sm font-semibold text-gray-700 w-36 text-center">{monthLabel}</span>
          <button
            onClick={nextMonth}
            className="px-2 py-1 text-sm text-gray-500 hover:text-gray-800 border border-gray-300 rounded"
          >
            ›
          </button>
          <button
            onClick={() => { setYear(today.getFullYear()); setMonth(today.getMonth()); }}
            className="px-2 py-1 text-xs text-blue-600 border border-blue-300 rounded hover:bg-blue-50"
          >
            Today
          </button>
        </div>
      </div>

      {/* Monthly summary */}
      <p className="text-xs text-gray-400 mb-4">
        {monthRuns > 0
          ? `${monthRuns} ${monthRuns === 1 ? "run" : "runs"} · ${fmtDist(monthDistM)}`
          : "No activities this month"}
      </p>

      {/* Day header row — 7 day names; weekly total lives in the gutter on the right */}
      <div className="flex mb-1">
        <div className="grid grid-cols-7 flex-1">
          {DAYS.map((d) => (
            <div key={d} className="text-center text-xs font-semibold text-gray-400 py-1">{d}</div>
          ))}
        </div>
        <div className="w-16 flex-shrink-0" aria-hidden />
      </div>

      {/* Calendar grid */}
      <div>
        {weeks.map((week, wi) => {
          const weekKey = localDateKey(week[0]);
          const isCurrentWeek = weekKey === todayWeekMonday;
          const isFirst = wi === 0;
          const isLast  = wi === weeks.length - 1;
          // Sum distance for all activities in this week
          const weekDistM = week.reduce((sum, day) => {
            const acts = byDate[localDateKey(day)] ?? [];
            return sum + acts.reduce((s, a) => s + (a.distance_m ?? 0), 0);
          }, 0);

          return (
            <div key={wi} className="flex items-stretch">
              {/* 7-day cells — fixed equal widths (minmax(0,1fr)), content wraps */}
              <div className={`grid grid-cols-7 flex-1 border-l border-t border-gray-200 overflow-hidden ${
                isLast ? "border-b" : ""
              } ${isFirst ? "rounded-t-lg" : ""} ${isLast ? "rounded-b-lg" : ""} ${
                isCurrentWeek ? "bg-blue-50/40" : ""
              }`}>
                {week.map((day, di) => {
                  const key = localDateKey(day);
                  const isCurrentMonth = day.getMonth() === month;
                  const isToday = key === todayKey;
                  const acts = byDate[key] ?? [];

                  return (
                    <div
                      key={di}
                      className={`border-r border-gray-200 min-h-[88px] p-1.5 ${
                        isCurrentMonth
                          ? isCurrentWeek ? "" : "bg-white"
                          : "bg-gray-50"
                      }`}
                    >
                      <div className={`text-xs font-medium mb-1 w-6 h-6 flex items-center justify-center rounded-full ${
                        isToday
                          ? "bg-blue-600 text-white"
                          : isCurrentMonth ? "text-gray-700" : "text-gray-300"
                      }`}>
                        {day.getDate()}
                      </div>
                      <div className="space-y-0.5">
                        {acts.map((act) => (
                          <Link
                            key={act.id}
                            to={`/activities/${act.id}`}
                            className={`block text-xs px-1.5 py-0.5 rounded border break-words leading-tight hover:opacity-80 transition-opacity ${sportColor(act.sport_type)}`}
                            title={`${formatActivityName(act)} — ${fmtDist(act.distance_m)}`}
                          >
                            <span className="font-medium">{fmtDist(act.distance_m)}</span>
                            {" "}
                            <span className="opacity-75">{formatActivityName(act)}</span>
                          </Link>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Weekly total — to the right of the week, no cell */}
              <div className="w-16 flex-shrink-0 flex items-center justify-end pl-2 pr-1">
                {weekDistM > 0 && (
                  <span className={`text-xs font-semibold tabular-nums ${
                    isCurrentWeek ? "text-blue-700" : "text-gray-500"
                  }`}>
                    {fmtDist(weekDistM)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
