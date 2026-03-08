import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from app.services.weather import fetch_weather, _wmo_label


def test_wmo_label_clear():
    assert _wmo_label(0) == "Clear"

def test_wmo_label_rain():
    assert _wmo_label(61) == "Rain"

def test_wmo_label_snow():
    assert _wmo_label(75) == "Snow"

def test_wmo_label_unknown():
    assert _wmo_label(999) == "Unknown"


def _mock_response():
    return {
        "hourly": {
            "time": [f"2024-05-01T{h:02d}:00" for h in range(24)],
            "temperature_2m":      [15.0] * 24,
            "apparent_temperature": [13.0] * 24,
            "precipitation":       [0.0] * 24,
            "cloudcover":          [20] * 24,
            "windspeed_10m":       [12.0] * 24,
            "weathercode":         [0] * 24,
        },
        "daily": {
            "sunrise": ["2024-05-01T05:30"],
            "sunset":  ["2024-05-01T20:15"],
        },
    }


def test_fetch_weather_returns_dict():
    started_at = datetime(2024, 5, 1, 8, 0, tzinfo=timezone.utc)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_response()
    with patch("httpx.get", return_value=mock_resp):
        result = fetch_weather(51.5, -0.1, started_at)
    assert result is not None
    assert result["weather_temp_c"] == 15.0
    assert result["weather_condition"] == "Clear"
    assert result["weather_is_daytime"] is True


def test_fetch_weather_returns_none_on_error():
    started_at = datetime(2024, 5, 1, 8, 0, tzinfo=timezone.utc)
    with patch("httpx.get", side_effect=Exception("network error")):
        result = fetch_weather(51.5, -0.1, started_at)
    assert result is None


def test_fetch_weather_before_sunrise():
    started_at = datetime(2024, 5, 1, 4, 0, tzinfo=timezone.utc)  # before 05:30
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_response()
    with patch("httpx.get", return_value=mock_resp):
        result = fetch_weather(51.5, -0.1, started_at)
    assert result["weather_is_daytime"] is False
