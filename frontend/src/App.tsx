import { lazy, Suspense, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Link } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UnitsProvider, useUnits } from "./contexts/UnitsContext";
import { getActivities, getStatsSummary, getPersonalBests, getVdot } from "./api/client";
import ActivityList from "./pages/ActivityList";
import Dashboard from "./pages/Dashboard";
import Gear from "./pages/Gear";
import Goals from "./pages/Goals";
import Plans from "./pages/Plans";
import PlanDetail from "./pages/PlanDetail";
import CalendarView from "./pages/CalendarView";
import Metrics from "./pages/Metrics";
import ErrorBoundary from "./components/ErrorBoundary";

// Lazy-load map-heavy pages so Leaflet only initialises when needed
const ActivityDetail = lazy(() => import("./pages/ActivityDetail"));
const Compare = lazy(() => import("./pages/Compare"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: Infinity,           // static files only change after writes
      gcTime: 1000 * 60 * 60,       // keep unused data in memory 1 hr
      refetchOnWindowFocus: false,
      refetchOnMount: false,         // use cached data when navigating back
    },
  },
});

// Kick off prefetches immediately — data will be ready before the user navigates
queryClient.prefetchQuery({ queryKey: ["activities"],              queryFn: getActivities,                    staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["stats-summary", "week"],  queryFn: () => getStatsSummary("week"),    staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["stats-summary", "month"], queryFn: () => getStatsSummary("month"),   staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["personal-bests"],         queryFn: getPersonalBests,                 staleTime: Infinity });
queryClient.prefetchQuery({ queryKey: ["vdot"],                   queryFn: getVdot,                          staleTime: Infinity });

const NAV_LINKS: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/activities", label: "Activities" },
  { to: "/compare", label: "Compare" },
  { to: "/calendar", label: "Calendar" },
  { to: "/gear", label: "Gear" },
  { to: "/goals", label: "Goals" },
  { to: "/plans", label: "Plans" },
  { to: "/metrics", label: "Metrics" },
];

function Nav() {
  const { system, toggle } = useUnits();
  const [menuOpen, setMenuOpen] = useState(false);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-2 rounded text-sm font-medium whitespace-nowrap ${
      isActive
        ? "bg-blue-700 text-white"
        : "text-blue-100 hover:bg-blue-700 hover:text-white"
    }`;

  return (
    <nav className="bg-blue-800 text-white px-4 py-2">
      {/* Desktop row */}
      <div className="flex items-center">
        {/* Left: brand */}
        <div className="flex-1">
          <Link to="/" className="font-bold text-lg text-white hover:text-blue-100 transition-colors">
            RunScribe
          </Link>
        </div>

        {/* Center: nav links (hidden on mobile) */}
        <div className="hidden md:flex items-center gap-1">
          {NAV_LINKS.map(({ to, label, end }) => (
            <NavLink key={to} to={to} end={end} className={linkClass}>
              {label}
            </NavLink>
          ))}
        </div>

        {/* Right: units toggle + hamburger */}
        <div className="flex-1 flex items-center justify-end gap-2">
          <button
            onClick={toggle}
            className="px-2.5 py-1 rounded text-xs font-semibold bg-blue-700 hover:bg-blue-600 text-blue-100 border border-blue-600 transition-colors"
            title="Toggle units"
          >
            {system === "imperial" ? "mi" : "km"}
          </button>

          {/* Hamburger — mobile only */}
          <button
            className="md:hidden flex flex-col gap-1 p-1.5 rounded hover:bg-blue-700 transition-colors"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Toggle menu"
          >
            <span className={`block h-0.5 w-5 bg-blue-100 transition-transform origin-center ${menuOpen ? "rotate-45 translate-y-1.5" : ""}`} />
            <span className={`block h-0.5 w-5 bg-blue-100 transition-opacity ${menuOpen ? "opacity-0" : ""}`} />
            <span className={`block h-0.5 w-5 bg-blue-100 transition-transform origin-center ${menuOpen ? "-rotate-45 -translate-y-1.5" : ""}`} />
          </button>
        </div>
      </div>

      {/* Mobile dropdown */}
      {menuOpen && (
        <div className="md:hidden flex flex-col gap-1 pt-2 pb-1 border-t border-blue-700 mt-2">
          {NAV_LINKS.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end as boolean | undefined}
              className={linkClass}
              onClick={() => setMenuOpen(false)}
            >
              {label}
            </NavLink>
          ))}
        </div>
      )}
    </nav>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <UnitsProvider>
        <BrowserRouter>
          <div className="min-h-screen">
            <Nav />
            <main>
              <ErrorBoundary>
                <Suspense fallback={<div className="p-8 text-center text-gray-400">Loading…</div>}>
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/activities" element={<ActivityList />} />
                    <Route path="/activities/:id" element={<ActivityDetail />} />
                    <Route path="/gear" element={<Gear />} />
                    <Route path="/goals" element={<Goals />} />
                    <Route path="/plans" element={<Plans />} />
                    <Route path="/plans/:id" element={<PlanDetail />} />
                    <Route path="/calendar" element={<CalendarView />} />
                    <Route path="/metrics" element={<Metrics />} />
                    <Route path="/compare" element={<Compare />} />
                  </Routes>
                </Suspense>
              </ErrorBoundary>
            </main>
          </div>
        </BrowserRouter>
      </UnitsProvider>
    </QueryClientProvider>
  );
}
