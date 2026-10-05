/**
 * App-wide configuration constants.
 * Edit this file to change global settings.
 */

// ── Units & Conversions ──────────────────────────────────────────────────────
/** Kilometres per mile */
export const KM_PER_MI = 1.60934;
/** Feet per metre */
export const FT_PER_M = 3.28084;

// ── Display ──────────────────────────────────────────────────────────────────
/** IANA timezone used for all date/time display in the app */
export const DISPLAY_TZ = "America/Los_Angeles";

/** Number of activities shown per page in the activity list */
export const PAGE_SIZE = 20;

// ── Gear ─────────────────────────────────────────────────────────────────────
/** Default shoe retirement threshold in miles */
export const SHOE_RETIREMENT_MI = 500;
/** Default shoe retirement threshold in kilometres */
export const SHOE_RETIREMENT_KM = 800;

// ── Charts ───────────────────────────────────────────────────────────────────
/** Ordered colour palette for multi-series charts (yearly overlay, etc.) */
export const CHART_COLORS = [
  "#3b82f6", // blue
  "#10b981", // emerald
  "#f59e0b", // amber
  "#ef4444", // red
  "#8b5cf6", // violet
  "#ec4899", // pink
];

// ── Themes ───────────────────────────────────────────────────────────────────
export type AppTheme = "default" | "solarized-dark" | "solarized-light";

export const THEMES: { key: AppTheme; label: string }[] = [
  { key: "default",        label: "Default" },
  { key: "solarized-dark", label: "Solarized Dark" },
  { key: "solarized-light","label": "Solarized Light" },
];

/** Theme used until the user explicitly picks one. index.html's pre-paint
 *  script hardcodes the same value; keep the two in sync. */
export const DEFAULT_THEME: AppTheme = "solarized-dark";

/** localStorage key holding an *explicit* theme choice. Deliberately not the
 *  old "theme" key: that one was rewritten on every load, so a stored
 *  "default" usually meant "never chose" rather than a real preference. */
export const THEME_STORAGE_KEY = "theme-choice";
