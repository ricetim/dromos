import httpx
from datetime import datetime, timezone

_WMO: dict[int, str] = {
    0: "Clear",
    1: "Partly cloudy", 2: "Partly cloudy",
    3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Rain", 53: "Rain", 55: "Rain",
    56: "Rain", 57: "Rain",
    61: "Rain", 63: "Rain", 65: "Rain",
    66: "Rain", 67: "Rain",
    71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow",
    80: "Rain", 81: "Rain", 82: "Rain",
    85: "Snow", 86: "Snow",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}


def _wmo_label(code: int) -> str:
    return _WMO.get(code, "Unknown")


def fetch_weather(lat: float, lon: float, started_at: datetime) -> dict | None:
    """
    Fetch hourly weather for the run's start location and time from Open-Meteo Archive.
    Returns a dict of weather fields ready to set on an Activity, or None on failure.
    """
    try:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        day = started_at.date().isoformat()
        r = httpx.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "start_date": day,
                "end_date": day,
                "hourly": "temperature_2m,apparent_temperature,precipitation,cloudcover,windspeed_10m,weathercode",
                "timezone": "UTC",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()

        hourly = data["hourly"]
        times = hourly["time"]  # list of "YYYY-MM-DDTHH:MM" strings

        # Find the index whose hour matches the run's start hour (UTC)
        run_hour = started_at.astimezone(timezone.utc).hour
        idx = next((i for i, t in enumerate(times) if int(t[11:13]) == run_hour), None)
        if idx is None:
            return None

        wmo_code = int(hourly["weathercode"][idx] or 0)
        # Sunrise/sunset are computed locally (see services/sun.py), not fetched.
        return {
            "weather_temp_c":       hourly["temperature_2m"][idx],
            "weather_feels_like_c": hourly["apparent_temperature"][idx],
            "weather_precip_mm":    hourly["precipitation"][idx],
            "weather_cloud_pct":    int(hourly["cloudcover"][idx] or 0),
            "weather_wind_kph":     hourly["windspeed_10m"][idx],
            "weather_condition":    _wmo_label(wmo_code),
        }
    except Exception:
        return None  # weather is non-critical; never block upload
