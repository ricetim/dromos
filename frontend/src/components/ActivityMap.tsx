import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { useTheme } from "../contexts/ThemeContext";
import { MapContainer, TileLayer, Polyline, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { DataPoint, Photo } from "../types";

// Leaflet's default icon URLs break under Vite's asset bundling — fix manually
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl:
    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl:
    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

// Tiles are served via the local caching proxy (/api/tiles/{provider}/{z}/{x}/{y}.png).
// First fetch hits the upstream provider; all subsequent loads are served from disk.
const TILE_LAYERS = {
  light: {
    label: "Light",
    url: "/api/tiles/light/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://openstreetmap.org">OSM</a> &copy; <a href="https://carto.com">CARTO</a>',
  },
  standard: {
    label: "Standard",
    url: "/api/tiles/standard/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://openstreetmap.org">OpenStreetMap</a>',
  },
  dark: {
    label: "Dark",
    url: "/api/tiles/dark/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://openstreetmap.org">OSM</a> &copy; <a href="https://carto.com">CARTO</a>',
  },
} as const;
type TileKey = keyof typeof TILE_LAYERS;

const cameraIcon = L.divIcon({
  html: `<div style="font-size:20px;line-height:1;cursor:pointer" title="Photo">📷</div>`,
  className: "",
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

// [lat, lon, speed_m_s | null] — compact format from /track endpoint
type TrackPoint = [number, number, number | null];

export interface ActivityMapHandle {
  updateHover(lat: number | null, lon: number | null): void;
}

interface Props {
  datapoints: DataPoint[];
  preloadedTrack?: TrackPoint[];  // fast-loading GPS+speed; if provided, used for map rendering
  photos?: Photo[];
  highlightRange?: [number, number] | null;
}

/** Captures the Leaflet map instance and manages the imperative hover dot. */
function HoverDotLayer({ dotRef }: { dotRef: React.MutableRefObject<L.CircleMarker | null> }) {
  const map = useMap();
  useEffect(() => {
    // Store map on dot ref container so the parent can call addTo/remove
    (dotRef as any)._map = map;
  }, [map, dotRef]);
  return null;
}

/** Fits the map to the highlighted segment when set, else the full track. */
function FitBounds({
  coords,
  highlightedCoords,
}: {
  coords: [number, number][];
  highlightedCoords?: [number, number][];
}) {
  const map = useMap();

  useEffect(() => {
    const target =
      highlightedCoords && highlightedCoords.length >= 2
        ? highlightedCoords
        : coords;
    if (target.length >= 2) {
      map.fitBounds(target as L.LatLngBoundsExpression, { padding: [24, 24] });
    }
  }, [highlightedCoords, coords, map]);

  return null;
}

/** Colours a polyline by a per-point value using a red→green scale. */
function ColouredTrack({
  segments,
}: {
  segments: { coords: [number, number][]; colour: string }[];
}) {
  const { theme } = useTheme();
  const isDark = theme === "solarized-dark";
  const outlineColor = isDark ? "#002b36" : "#ffffff";
  return (
    <>
      {segments.map((seg, i) => (
        <Polyline key={`shadow-${i}`} positions={seg.coords} color="#000000" weight={6} opacity={0.15} />
      ))}
      {segments.map((seg, i) => (
        <Polyline key={`outline-${i}`} positions={seg.coords} color={outlineColor} weight={5} opacity={0.9} />
      ))}
      {segments.map((seg, i) => (
        <Polyline key={`track-${i}`} positions={seg.coords} color={seg.colour} weight={3} />
      ))}
    </>
  );
}

/** Build coloured segments from speed data (green = fast, red = slow). */
function buildPaceSegments(
  datapoints: DataPoint[]
): { coords: [number, number][]; colour: string }[] {
  const withGps = datapoints.filter(
    (dp) => dp.lat !== null && dp.lon !== null && dp.speed_m_s !== null
  );
  if (withGps.length < 2) return [];

  const speeds = withGps.map((dp) => dp.speed_m_s!);
  const minSpeed = Math.min(...speeds);
  const maxSpeed = Math.max(...speeds);
  const range = maxSpeed - minSpeed || 1;

  const segments: { coords: [number, number][]; colour: string }[] = [];
  for (let i = 0; i < withGps.length - 1; i++) {
    const dp = withGps[i];
    const next = withGps[i + 1];
    const t = (dp.speed_m_s! - minSpeed) / range; // 0 = slow, 1 = fast
    // Interpolate red (#ef4444) → yellow (#eab308) → green (#22c55e)
    const r = t < 0.5 ? 239 : Math.round(239 - (t - 0.5) * 2 * (239 - 34));
    const g = t < 0.5 ? Math.round(t * 2 * 163) : Math.round(163 + (t - 0.5) * 2 * (197 - 163));
    const b = t < 0.5 ? 68 : Math.round(68 + (t - 0.5) * 2 * (94 - 68));
    segments.push({
      coords: [
        [dp.lat!, dp.lon!],
        [next.lat!, next.lon!],
      ],
      colour: `rgb(${r},${g},${b})`,
    });
  }
  return segments;
}

const ActivityMap = forwardRef<ActivityMapHandle, Props>(function ActivityMap(
  { datapoints, preloadedTrack, photos = [], highlightRange }: Props,
  ref,
) {
  const { theme } = useTheme();
  const [tileKey, setTileKey] = useState<TileKey>(theme === "solarized-dark" ? "dark" : "light");
  const hoverDotRef = useRef<L.CircleMarker | null>(null);

  useEffect(() => {
    setTileKey(theme === "solarized-dark" ? "dark" : "light");
  }, [theme]);

  useImperativeHandle(ref, () => ({
    updateHover(lat: number | null, lon: number | null) {
      const map: L.Map | undefined = (hoverDotRef as any)._map;
      if (hoverDotRef.current) {
        hoverDotRef.current.remove();
        hoverDotRef.current = null;
      }
      if (lat != null && lon != null && map) {
        hoverDotRef.current = L.circleMarker([lat, lon], {
          radius: 7,
          color: "#fff",
          fillColor: "#3b82f6",
          fillOpacity: 1,
          weight: 2,
        }).addTo(map);
      }
    },
  }));

  // Use preloadedTrack for coords + pace segments if available (loads fast).
  // Full datapoints are still used for hover marker and highlight range.
  const coords: [number, number][] = useMemo(() => {
    if (preloadedTrack?.length) return preloadedTrack.map(([lat, lon]) => [lat, lon]);
    return datapoints
      .filter((dp) => dp.lat !== null && dp.lon !== null)
      .map((dp) => [dp.lat!, dp.lon!]);
  }, [preloadedTrack, datapoints]);

  const paceSegments = useMemo(() => {
    if (preloadedTrack?.length) {
      const pts = preloadedTrack.filter(([,, s]) => s !== null);
      if (pts.length < 2) return [];
      const speeds = pts.map(([,, s]) => s!);
      const minSpeed = Math.min(...speeds);
      const maxSpeed = Math.max(...speeds);
      const spd_range = maxSpeed - minSpeed || 1;
      return pts.slice(0, -1).map((pt, i) => {
        const next = pts[i + 1];
        const t = (pt[2]! - minSpeed) / spd_range;
        const r = t < 0.5 ? 239 : Math.round(239 - (t - 0.5) * 2 * (239 - 34));
        const g = t < 0.5 ? Math.round(t * 2 * 163) : Math.round(163 + (t - 0.5) * 2 * (197 - 163));
        const b = t < 0.5 ? 68 : Math.round(68 + (t - 0.5) * 2 * (94 - 68));
        return { coords: [[pt[0], pt[1]], [next[0], next[1]]] as [number, number][], colour: `rgb(${r},${g},${b})` };
      });
    }
    return buildPaceSegments(datapoints);
  }, [preloadedTrack, datapoints]);

  const highlighted: [number, number][] = useMemo(() => {
    if (!highlightRange) return [];
    const gps = datapoints.filter((dp) => dp.lat !== null && dp.lon !== null);
    return gps
      .slice(highlightRange[0], highlightRange[1])
      .map((dp) => [dp.lat!, dp.lon!]);
  }, [datapoints, highlightRange]);

  const gpsPhotos = useMemo(
    () => photos.filter((p) => p.lat !== null && p.lon !== null),
    [photos]
  );

  if (coords.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center bg-gray-100 rounded-lg text-gray-400">
        No GPS data available
      </div>
    );
  }

  const tile = TILE_LAYERS[tileKey];

  return (
    <div className="relative">
      {/* Tile layer selector */}
      <div className="absolute top-2 right-2 z-[1000] flex gap-1 bg-white/90 backdrop-blur-sm rounded-lg border border-gray-200 shadow px-1.5 py-1">
        {(Object.keys(TILE_LAYERS) as TileKey[]).map((k) => (
          <button
            key={k}
            onClick={() => setTileKey(k)}
            className={`px-2 py-0.5 text-xs rounded transition-colors ${
              tileKey === k
                ? "bg-gray-800 text-white"
                : "text-gray-600 hover:bg-gray-100"
            }`}
          >
            {TILE_LAYERS[k].label}
          </button>
        ))}
      </div>
    <MapContainer
      center={coords[0]}
      zoom={13}
      style={{ height: 420, borderRadius: 8 }}
      className="z-0"
    >
      <TileLayer url={tile.url} attribution={tile.attribution} />
      <FitBounds
        coords={coords}
        highlightedCoords={highlighted.length >= 2 ? highlighted : undefined}
      />

      {/* Pace-coloured track */}
      {paceSegments.length > 0 ? (
        <ColouredTrack segments={paceSegments} />
      ) : (
        <>
          <Polyline positions={coords} color={theme === "solarized-dark" ? "#002b36" : "#ffffff"} weight={5} opacity={0.8} />
          <Polyline positions={coords} color="#3b82f6" weight={3} />
        </>
      )}

      {/* Brush-selected highlight */}
      {highlighted.length > 1 && (
        <Polyline positions={highlighted} color="#f97316" weight={5} opacity={0.9} />
      )}

      {/* Imperative hover dot — updated directly without React re-renders */}
      <HoverDotLayer dotRef={hoverDotRef} />

      {/* GPS-tagged photo markers */}
      {gpsPhotos.map((photo) => (
        <Marker
          key={photo.id}
          position={[photo.lat!, photo.lon!]}
          icon={cameraIcon}
        >
          <Popup maxWidth={300}>
            <img
              src={photo.url}
              alt="Run photo"
              style={{ maxWidth: 280, maxHeight: 200, objectFit: "cover", borderRadius: 4 }}
            />
          </Popup>
        </Marker>
      ))}
    </MapContainer>
    </div>
  );
});

export default ActivityMap;
