"""Local sunrise/sunset computation — no network required.

Sunrise/sunset is pure astronomy (a function of latitude, longitude and date),
so it's computed locally via the standard "sunrise equation" rather than looked
up. Accurate to ~1 minute at non-polar latitudes, which is plenty for a running
log. This supersedes the old Open-Meteo sun fields (which were fetched, then
discarded, and whose is-daytime check broke across the UTC date boundary).

Actual weather (temperature, precipitation, cloud cover) still needs the network
— only the sun times moved local.
"""
import math
from datetime import date, datetime, timedelta, timezone

_RAD = math.pi / 180.0
# Standard sunrise/sunset altitude: −0.833° accounts for atmospheric refraction
# plus the sun's apparent radius (centre is below the geometric horizon at the
# moment the upper limb touches it).
_HORIZON = -0.833


def _julian_date_midnight_utc(d: date) -> float:
    """Julian date at 00:00 UTC for a Gregorian calendar date."""
    y, m, day = d.year, d.month, d.day
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    jdn = (day + (153 * mm + 2) // 5 + 365 * yy + yy // 4
           - yy // 100 + yy // 400 - 32045)
    return jdn - 0.5  # JDN is referenced to noon; step back to 00:00 UTC


def _jd_to_datetime(jd: float) -> datetime:
    """Julian date → naive UTC datetime (rounded to the second)."""
    unix = (jd - 2440587.5) * 86400.0
    return datetime(1970, 1, 1) + timedelta(seconds=round(unix))


def sun_times(lat: float, lon: float, d: date) -> tuple[datetime | None, datetime | None]:
    """(sunrise, sunset) as naive UTC datetimes for the given location and date,
    or (None, None) when the sun never crosses the horizon (polar day/night).

    Longitude is east-positive (e.g. Portland ≈ -122.68)."""
    # Integer day number since the J2000 epoch (2000-01-01 12:00 UTC).
    n = math.ceil(_julian_date_midnight_utc(d) - 2451545.0 + 0.0008)
    # Mean solar time. lon is east-positive, so the longitude correction that
    # delays solar noon for western locations is -lon/360 (e.g. Portland's
    # -122.68° pushes solar noon ~8h later than UTC noon).
    j_star = n - lon / 360.0
    # Solar mean anomaly.
    M = (357.5291 + 0.98560028 * j_star) % 360.0
    # Equation of the centre.
    C = (1.9148 * math.sin(M * _RAD)
         + 0.0200 * math.sin(2 * M * _RAD)
         + 0.0003 * math.sin(3 * M * _RAD))
    # Ecliptic longitude.
    lam = (M + C + 180.0 + 102.9372) % 360.0
    # Solar transit (Julian date of solar noon).
    j_transit = (2451545.0 + j_star
                 + 0.0053 * math.sin(M * _RAD)
                 - 0.0069 * math.sin(2 * lam * _RAD))
    # Solar declination.
    sin_dec = math.sin(lam * _RAD) * math.sin(23.4397 * _RAD)
    dec = math.asin(sin_dec)
    # Hour angle at the horizon.
    cos_omega = ((math.sin(_HORIZON * _RAD) - math.sin(lat * _RAD) * sin_dec)
                 / (math.cos(lat * _RAD) * math.cos(dec)))
    if not -1.0 <= cos_omega <= 1.0:
        return None, None  # polar day or night
    omega = math.acos(cos_omega) / _RAD  # degrees
    return (_jd_to_datetime(j_transit - omega / 360.0),
            _jd_to_datetime(j_transit + omega / 360.0))


def sun_fields(lat: float, lon: float, started_at: datetime) -> dict:
    """Sunrise/sunset fields (naive UTC datetimes) for the run's *local* day,
    ready to set on an Activity. Uses longitude as a timezone proxy so an
    evening run whose UTC timestamp has rolled past midnight still resolves to
    the correct local calendar day."""
    utc = (started_at.astimezone(timezone.utc).replace(tzinfo=None)
           if started_at.tzinfo is not None else started_at)
    local_date = (utc + timedelta(hours=lon / 15.0)).date()
    rise, sett = sun_times(lat, lon, local_date)
    return {"sunrise": rise, "sunset": sett}


def backfill_sun_times(session) -> int:
    """Populate sunrise/sunset for activities missing them, using each run's
    first GPS fix. Fully offline. Returns the number updated."""
    from sqlmodel import select
    from app.models import Activity, DataPoint

    acts = session.exec(select(Activity).where(Activity.sunrise.is_(None))).all()
    updated = 0
    for a in acts:
        gp = session.exec(
            select(DataPoint.lat, DataPoint.lon)
            .where(DataPoint.activity_id == a.id)
            .where(DataPoint.lat.is_not(None))
            .where(DataPoint.lon.is_not(None))
            .order_by(DataPoint.timestamp)
            .limit(1)
        ).first()
        if not gp:
            continue
        fields = sun_fields(gp[0], gp[1], a.started_at)
        if fields["sunrise"] is None:
            continue
        a.sunrise = fields["sunrise"]
        a.sunset = fields["sunset"]
        session.add(a)
        updated += 1
    if updated:
        session.commit()
    return updated
