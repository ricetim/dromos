import httpx
from app.config import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN

_API = "https://www.strava.com/api/v3"


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    r = httpx.post("https://www.strava.com/oauth/token", data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    })
    return r.json()["access_token"]


def get_access_token() -> str:
    return refresh_access_token(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN)


def _check(r: httpx.Response) -> httpx.Response:
    """Raise a clear error on non-2xx Strava responses (including 429 rate limit)."""
    if r.status_code == 429:
        raise RuntimeError(f"Strava rate limit exceeded (429). Retry in ~15 minutes.")
    r.raise_for_status()
    return r


def fetch_athlete(access_token: str) -> dict:
    """Return the authenticated athlete's profile (includes the 'shoes' array)."""
    r = httpx.get(f"{_API}/athlete", headers={"Authorization": f"Bearer {access_token}"})
    return _check(r).json()


def fetch_athlete_activities(access_token: str, after: int = 0) -> list[dict]:
    """
    Paginate through all athlete activities since `after` (unix timestamp).
    Each item includes at minimum: id, start_date (UTC ISO), gear_id (nullable).
    """
    results: list[dict] = []
    page = 1
    with httpx.Client(timeout=30) as client:
        while True:
            r = client.get(
                f"{_API}/athlete/activities",
                params={"per_page": 200, "page": page, "after": after},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            batch = _check(r).json()
            if not isinstance(batch, list) or not batch:
                break
            results.extend(batch)
            if len(batch) < 200:
                break
            page += 1
    return results


def fetch_gear(access_token: str, gear_id: str) -> dict | None:
    """Fetch a single gear item by Strava gear_id (e.g. 'g27724348')."""
    try:
        r = httpx.get(
            f"{_API}/gear/{gear_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        _check(r)
        return r.json()
    except Exception:
        return None


_STREAM_KEYS = "time,latlng,altitude,heartrate,cadence,velocity_smooth,distance"


def fetch_activity_streams(access_token: str, strava_activity_id: str) -> dict:
    """
    Fetch activity streams keyed by type.
    Returns dict like: {"time": {"data": [...]}, "latlng": {"data": [...]}, ...}
    """
    r = httpx.get(
        f"{_API}/activities/{strava_activity_id}/streams",
        params={"keys": _STREAM_KEYS, "key_by_type": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    _check(r)
    return r.json()


def fetch_activity_laps(access_token: str, strava_activity_id: str) -> list[dict]:
    """Fetch laps for a Strava activity. Returns raw lap dicts."""
    r = httpx.get(
        f"{_API}/activities/{strava_activity_id}/laps",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    _check(r)
    data = r.json()
    return data if isinstance(data, list) else []


def streams_to_datapoints(streams: dict, started_at) -> list[dict]:
    """Convert keyed stream dict → list of datapoint dicts (timestamp-stamped)."""
    from datetime import timedelta
    times    = streams.get("time",             {}).get("data", [])
    latlngs  = streams.get("latlng",           {}).get("data", [])
    alts     = streams.get("altitude",         {}).get("data", [])
    hrs      = streams.get("heartrate",        {}).get("data", [])
    cads     = streams.get("cadence",          {}).get("data", [])
    speeds   = streams.get("velocity_smooth",  {}).get("data", [])
    dists    = streams.get("distance",         {}).get("data", [])

    dps = []
    for i, t_s in enumerate(times):
        dps.append({
            "timestamp":  started_at + timedelta(seconds=int(t_s)),
            "lat":        latlngs[i][0] if i < len(latlngs) else None,
            "lon":        latlngs[i][1] if i < len(latlngs) else None,
            "altitude_m": alts[i]       if i < len(alts)    else None,
            "heart_rate": round(hrs[i]) if i < len(hrs)     else None,
            "cadence":    round(cads[i])if i < len(cads)    else None,
            "speed_m_s":  speeds[i]     if i < len(speeds)  else None,
            "distance_m": dists[i]      if i < len(dists)   else None,
        })
    return dps


def fetch_activity_photos(access_token: str, strava_activity_id: str) -> list[dict]:
    r = httpx.get(
        f"{_API}/activities/{strava_activity_id}/photos",
        params={"photo_sources": "true", "size": 1200},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    _check(r)
    data = r.json()
    return data if isinstance(data, list) else []


def sync_photos_for_activity(activity, session, access_token: str | None = None) -> int:
    from app.models import Photo
    from app.services.exif import extract_gps_from_url
    from sqlmodel import select
    if not activity.strava_id:
        return 0
    token = access_token or get_access_token()
    photos = fetch_activity_photos(token, activity.strava_id)
    existing = {p.strava_photo_id for p in
                session.exec(select(Photo).where(Photo.activity_id == activity.id)).all()}
    count = 0
    for p in photos:
        uid = str(p.get("unique_id", ""))
        if uid in existing:
            continue
        urls = p.get("urls", {})
        url = urls.get("1200") or urls.get("600") or next(iter(urls.values()), None)
        if not url:
            continue
        lat, lon = extract_gps_from_url(url)
        session.add(Photo(activity_id=activity.id, strava_photo_id=uid,
                          url=url, lat=lat, lon=lon))
        count += 1
    session.commit()
    return count
