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


def fetch_activity_photos(access_token: str, strava_activity_id: str) -> list[dict]:
    r = httpx.get(
        f"{_API}/activities/{strava_activity_id}/photos",
        params={"photo_sources": "true", "size": 1200},
        headers={"Authorization": f"Bearer {access_token}"},
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
