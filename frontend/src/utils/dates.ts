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
