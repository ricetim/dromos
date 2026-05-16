export interface Activity {
  id: number;
  source: string;
  started_at: string;
  distance_m: number;
  duration_s: number;
  elevation_gain_m: number;
  elevation_loss_m: number | null;
  avg_hr: number | null;
  avg_pace_s_per_km: number | null;
  sport_type: string;
  notes: string | null;
  rpe: number | null;
  strava_id: string | null;
  name?: string | null;
  weather_temp_c?: number | null;
  weather_feels_like_c?: number | null;
  weather_precip_mm?: number | null;
  weather_cloud_pct?: number | null;
  weather_wind_kph?: number | null;
  weather_condition?: string | null;
  weather_is_daytime?: boolean | null;
  track?: [number, number][];
  shoe_names?: string[];
  shoes?: { id: number; name: string; brand: string | null }[];
}

export interface DataPoint {
  id: number;
  activity_id: number;
  timestamp: string;
  lat: number | null;
  lon: number | null;
  distance_m: number | null;
  speed_m_s: number | null;
  heart_rate: number | null;
  cadence: number | null;
  altitude_m: number | null;
  power_w: number | null;
  vertical_oscillation_mm: number | null;
  stride_length_m: number | null;
  vertical_ratio: number | null;
  stance_time_ms: number | null;
}

export interface Photo {
  id: number;
  activity_id: number;
  url: string;
  captured_at: string | null;
  lat: number | null;
  lon: number | null;
}

export interface Shoe {
  id: number;
  name: string;
  brand: string | null;
  retired: boolean;
  retirement_threshold_km: number;
  total_distance_km?: number;
}

export interface Goal {
  id: number;
  type: string;
  target_value: number;
  period_start: string;
  period_end: string;
  notes: string | null;
}

