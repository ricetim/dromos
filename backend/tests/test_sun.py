from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.services.sun import sun_times, sun_fields

PT = ZoneInfo("America/Los_Angeles")
PORTLAND = (45.5152, -122.6784)


def _pt(dt: datetime) -> datetime:
    """Interpret a naive UTC datetime in Pacific time."""
    return dt.replace(tzinfo=timezone.utc).astimezone(PT)


def test_portland_summer_solstice_matches_reference():
    # timeanddate.com, Portland OR 2026-06-21: sunrise 05:22, sunset 21:03.
    rise, sett = sun_times(*PORTLAND, date(2026, 6, 21))
    r, s = _pt(rise), _pt(sett)
    assert (r.hour, r.minute) == (5, 21) or abs(r.minute - 22) <= 2
    assert s.hour == 21 and abs(s.minute - 3) <= 2


def test_portland_winter_solstice_matches_reference():
    # Reference: sunrise ~07:49, sunset ~16:31.
    rise, sett = sun_times(*PORTLAND, date(2026, 12, 21))
    r, s = _pt(rise), _pt(sett)
    assert r.hour == 7 and abs(r.minute - 49) <= 3
    assert s.hour == 16 and abs(s.minute - 31) <= 3


def test_sunrise_before_sunset_and_daylight_plausible():
    rise, sett = sun_times(*PORTLAND, date(2026, 6, 21))
    assert rise < sett
    daylight_h = (sett - rise).total_seconds() / 3600
    assert 15 < daylight_h < 16  # long summer day in Portland


def test_polar_night_returns_none():
    # Tromsø, Norway in deep winter: sun never rises.
    rise, sett = sun_times(69.65, 18.96, date(2026, 12, 21))
    assert rise is None and sett is None


def test_sun_fields_uses_local_day_across_utc_midnight():
    # 9pm PT run: UTC timestamp is already the next calendar day, but the
    # sunrise should still be that evening's local day, not the UTC day.
    started = datetime(2026, 6, 21, 21, 0, tzinfo=PT).astimezone(timezone.utc).replace(tzinfo=None)
    fields = sun_fields(*PORTLAND, started)
    assert fields["sunrise"] is not None
    r = _pt(fields["sunrise"])
    assert r.month == 6 and r.day == 21 and r.hour == 5


def test_sun_fields_handles_naive_and_aware_input():
    aware = datetime(2026, 6, 21, 14, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 6, 21, 14, 0)
    assert sun_fields(*PORTLAND, aware) == sun_fields(*PORTLAND, naive)
