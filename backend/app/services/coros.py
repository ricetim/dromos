"""
Coros sync via reverse-engineered Training Hub API.
References: jmn8718/coros-connect, gandroz/coros_data_extractor, cygnusb/coros-mcp
"""
import hashlib
import httpx
from app.config import COROS_EMAIL, COROS_PASSWORD

BASE = "https://teamapi.coros.com"


def _headers(token: str, user_id: str = "") -> dict:
    h = {"accessToken": token}
    if user_id:
        h["yfheader"] = f'{{"userId":"{user_id}"}}'
    return h


def login(email: str, password: str) -> tuple[str, str]:
    """Returns (accessToken, userId). Password is MD5-hashed before sending."""
    pwd_hash = hashlib.md5(password.encode()).hexdigest()
    r = httpx.post(
        f"{BASE}/account/login",
        json={"account": email, "accountType": 2, "pwd": pwd_hash},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json().get("data", {})
    return data["accessToken"], str(data.get("userId", ""))


def list_activities(token: str, user_id: str = "", page: int = 1, size: int = 50) -> list[dict]:
    r = httpx.get(
        f"{BASE}/activity/query",
        params={"pageNumber": page, "size": size, "modeList": ""},
        headers=_headers(token, user_id),
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("data", {}).get("dataList", [])


def download_fit(token: str, user_id: str, label_id: str, sport_type: str) -> bytes:
    """Get a pre-signed S3 URL then download the FIT file (fileType=4)."""
    r = httpx.post(
        f"{BASE}/activity/detail/download",
        params={"labelId": label_id, "sportType": sport_type, "fileType": 4},
        headers=_headers(token, user_id),
        timeout=15,
    )
    r.raise_for_status()
    url = r.json()["data"]["fileUrl"]
    return httpx.get(url, timeout=60).content


def get_activity_detail_raw(token: str, user_id: str, label_id: str, sport_type: str) -> dict:
    """Full, unparsed `data` object from the activity-detail endpoint.

    Used for debugging/discovery (e.g. hunting for the rest-vs-run interval
    structure the Coros app shows but the FIT file omits). Unlike
    get_activity_detail() this returns everything, not just RPE/notes.
    """
    r = httpx.post(
        f"{BASE}/activity/detail/query",
        params={"labelId": label_id, "sportType": sport_type},
        headers=_headers(token, user_id),
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("data", {})


def get_activity_detail(token: str, user_id: str, label_id: str, sport_type: str) -> dict:
    """
    Fetch activity detail. Returns dict with:
      rpe   — int 1-5 (Coros feelType: 1=Very Easy … 5=Maximum)
      notes — str | None (Coros sportNote)
    """
    try:
        r = httpx.post(
            f"{BASE}/activity/detail/query",
            params={"labelId": label_id, "sportType": sport_type},
            headers=_headers(token, user_id),
            timeout=15,
        )
        r.raise_for_status()
        feel = r.json().get("data", {}).get("sportFeelInfo", {})
        return {
            "rpe": feel.get("feelType"),
            "notes": feel.get("sportNote") or None,
        }
    except Exception:
        return {"rpe": None, "notes": None}
