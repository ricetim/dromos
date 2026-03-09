"""Tests for Strava service and EXIF extraction."""
from unittest.mock import patch, MagicMock
from app.services.strava import refresh_access_token, fetch_activity_photos, fetch_activity_laps
from app.services.exif import extract_gps_from_url


def test_refresh_token():
    mock = MagicMock()
    mock.json.return_value = {"access_token": "tok123", "expires_at": 9999999999}
    with patch("httpx.post", return_value=mock):
        assert refresh_access_token("cid", "csec", "rtok") == "tok123"


def test_fetch_photos_empty():
    mock = MagicMock()
    mock.json.return_value = []
    with patch("httpx.get", return_value=mock):
        assert fetch_activity_photos("token", "123") == []


def test_extract_gps_no_exif():
    # Image with no EXIF GPS should return (None, None)
    mock = MagicMock()
    mock.content = b"not an image"
    with patch("httpx.get", return_value=mock):
        lat, lon = extract_gps_from_url("http://example.com/photo.jpg")
    assert lat is None and lon is None


def test_fetch_activity_laps():
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = [
        {
            "lap_index": 1,
            "elapsed_time": 482,
            "distance": 1609.34,
            "average_heartrate": 148.5,
            "average_speed": 3.34,
            "total_elevation_gain": 5.2,
            "start_date": "2025-09-15T13:00:00Z",
        }
    ]
    with patch("httpx.get", return_value=mock):
        laps = fetch_activity_laps("token", "99999")
    assert len(laps) == 1
    assert laps[0]["lap_index"] == 1
    assert laps[0]["elapsed_time"] == 482
