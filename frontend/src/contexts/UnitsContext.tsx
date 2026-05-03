import { createContext, useContext, useState, ReactNode } from "react";
import { KM_PER_MI, FT_PER_M } from "../config";

type System = "imperial" | "metric";

interface UnitsCtx {
  system: System;
  toggle: () => void;
  /** Metres → formatted distance string */
  fmtDist: (m: number) => string;
  /** Seconds-per-km → formatted pace string */
  fmtPace: (sPerKm: number | null) => string;
  /** Metres → formatted elevation string */
  fmtElev: (m: number) => string;
  /** Shoe km → formatted distance string */
  fmtShoe: (km: number) => string;
  /** Celsius → formatted temperature string (°F imperial, °C metric) */
  fmtTemp: (c: number) => string;
  /** Millimetres precipitation → formatted string (in imperial, mm metric) */
  fmtPrecip: (mm: number) => string;
}

const Ctx = createContext<UnitsCtx | null>(null);

export function UnitsProvider({ children }: { children: ReactNode }) {
  const [system, setSystem] = useState<System>(
    () => (localStorage.getItem("units") as System | null) ?? "imperial"
  );

  function toggle() {
    setSystem((s) => {
      const next = s === "imperial" ? "metric" : "imperial";
      localStorage.setItem("units", next);
      return next;
    });
  }

  function fmtDist(m: number): string {
    if (system === "imperial") {
      return (m / 1000 / KM_PER_MI).toFixed(2) + " mi";
    }
    return (m / 1000).toFixed(2) + " km";
  }

  function fmtPace(sPerKm: number | null): string {
    if (!sPerKm) return "—";
    const s = system === "imperial" ? sPerKm * KM_PER_MI : sPerKm;
    const unit = system === "imperial" ? "/mi" : "/km";
    const m = Math.floor(s / 60);
    const sec = Math.round(s % 60).toString().padStart(2, "0");
    return `${m}:${sec} ${unit}`;
  }

  function fmtElev(m: number): string {
    if (system === "imperial") return Math.round(m * FT_PER_M) + " ft";
    return Math.round(m) + " m";
  }

  function fmtShoe(km: number): string {
    if (system === "imperial") return (km / KM_PER_MI).toFixed(0) + " mi";
    return km.toFixed(0) + " km";
  }

  function fmtTemp(c: number): string {
    if (system === "imperial") return `${Math.round(c * 9 / 5 + 32)}°F`;
    return `${Math.round(c)}°C`;
  }

  function fmtPrecip(mm: number): string {
    if (system === "imperial") return `${(mm / 25.4).toFixed(2)} in`;
    return `${mm.toFixed(1)} mm`;
  }

  return (
    <Ctx.Provider value={{ system, toggle, fmtDist, fmtPace, fmtElev, fmtShoe, fmtTemp, fmtPrecip }}>
      {children}
    </Ctx.Provider>
  );
}

export function useUnits(): UnitsCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useUnits must be used within UnitsProvider");
  return ctx;
}
