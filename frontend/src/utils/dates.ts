import { DISPLAY_TZ as TZ } from "../config";

/** "Mon, Jan 15, 2024" */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "short", month: "short", day: "numeric", year: "numeric",
    timeZone: TZ,
  });
}

/** "Monday, January 15, 2024" */
export function formatDateLong(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
    timeZone: TZ,
  });
}

/** "Jan 15, 2024" */
export function formatDateShort(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    timeZone: TZ,
  });
}

/** "Mon, Jan 15" */
export function formatDateMonthDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    timeZone: TZ,
  });
}

/** "Jan 15" */
export function formatDateShortNoYear(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short", day: "numeric",
    timeZone: TZ,
  });
}

/** "7:05 AM" */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit", minute: "2-digit",
    timeZone: TZ,
  });
}

// ── plain calendar-day keys (YYYY-MM-DD) ─────────────────────────────────────

/** YYYY-MM-DD of a stored (naive-UTC) timestamp in the display timezone.
 *  started_at has no offset suffix, so append "Z" to anchor it to UTC before
 *  converting; the day then flips at local (Pacific) midnight, matching the
 *  backend's day-bucketing (services/builder.py via stats._local_date). */
export function displayDateKey(iso: string): string {
  const utc = /[Z]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(utc));
  const get = (t: string) => parts.find((p) => p.type === t)!.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Parse a plain "YYYY-MM-DD" key into a Date at local midnight (no tz shift). */
function dateKeyToLocal(key: string): Date {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Shift a plain "YYYY-MM-DD" key by `days` (calendar arithmetic, no tz shift). */
export function addDaysToDateKey(key: string, days: number): string {
  const dt = dateKeyToLocal(key);
  dt.setDate(dt.getDate() + days);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
}

/** Format a plain "YYYY-MM-DD" key as a wall-calendar date (no tz shift).
 *  Defaults to e.g. "Wed, Jun 17". */
export function formatDateKey(key: string, opts?: Intl.DateTimeFormatOptions): string {
  return dateKeyToLocal(key).toLocaleDateString("en-US",
    opts ?? { weekday: "short", month: "short", day: "numeric" });
}
