import pytest
from pathlib import Path
from app.models import Activity, ActivityShoe, DataPoint, EventLog, Lap, Shoe
from datetime import datetime

FIXTURE = Path(__file__).parent / "fixtures" / "sample.fit"


def test_get_activity_photos_nonexistent(client):
    r = client.get("/api/activities/999/photos")
    assert r.status_code == 404


def test_upload_invalid_file(client, tmp_path, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    r = client.post(
        "/api/activities/upload",
        files={"file": ("bad.fit", b"not a fit file", "application/octet-stream")},
    )
    assert r.status_code == 422


@pytest.mark.skipif(not FIXTURE.exists(), reason="no sample.fit fixture")
def test_upload_fit_file(client, tmp_path, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    with open(FIXTURE, "rb") as f:
        r = client.post(
            "/api/activities/upload",
            files={"file": ("run.fit", f, "application/octet-stream")},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] is not None
    assert body["distance_m"] > 0
    assert body["source"] == "manual_upload"


@pytest.mark.skipif(not FIXTURE.exists(), reason="no sample.fit fixture")
def test_upload_persists_activity(client, session, tmp_path, monkeypatch):
    import app.config as cfg
    from sqlmodel import select as sm_select
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    with open(FIXTURE, "rb") as f:
        client.post("/api/activities/upload",
                    files={"file": ("run.fit", f, "application/octet-stream")})
    # Reads are served from static JSON, not an endpoint — assert the row landed.
    acts = session.exec(sm_select(Activity)).all()
    assert len(acts) == 1


def _make_activity(session):
    act = Activity(
        source="manual_upload",
        sport_type="running",
        started_at=datetime(2024, 1, 1, 8, 0, 0),
        duration_s=3600,
        distance_m=10000,
        elevation_gain_m=50,
    )
    session.add(act)
    session.commit()
    session.refresh(act)
    return act


def _make_shoe(session, name="Pegasus"):
    shoe = Shoe(name=name, brand="Nike", retired=False)
    session.add(shoe)
    session.commit()
    session.refresh(shoe)
    return shoe


def test_patch_activity_shoe_assigns(client, session):
    from sqlmodel import select as sm_select
    act = _make_activity(session)
    shoe = _make_shoe(session)
    r = client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": shoe.id})
    assert r.status_code == 200
    links = session.exec(sm_select(ActivityShoe).where(ActivityShoe.activity_id == act.id)).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe.id


def test_patch_activity_shoe_replaces(client, session):
    from sqlmodel import select as sm_select
    act = _make_activity(session)
    shoe1 = _make_shoe(session, "Shoe A")
    shoe2 = _make_shoe(session, "Shoe B")
    client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": shoe1.id})
    r = client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": shoe2.id})
    assert r.status_code == 200
    links = session.exec(sm_select(ActivityShoe).where(ActivityShoe.activity_id == act.id)).all()
    assert len(links) == 1
    assert links[0].shoe_id == shoe2.id


def test_patch_activity_shoe_clears(client, session):
    from sqlmodel import select as sm_select
    act = _make_activity(session)
    shoe = _make_shoe(session)
    client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": shoe.id})
    r = client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": None})
    assert r.status_code == 200
    links = session.exec(sm_select(ActivityShoe).where(ActivityShoe.activity_id == act.id)).all()
    assert len(links) == 0


def test_delete_activity_removes_laps_datapoints_and_logs(client, session):
    from sqlmodel import select as sm_select
    act = _make_activity(session)
    session.add(DataPoint(activity_id=act.id, timestamp=datetime(2024, 1, 1, 8, 0, 0)))
    session.add(Lap(
        activity_id=act.id, lap_number=1,
        start_elapsed_s=0, end_elapsed_s=600, distance_m=2000, duration_s=600,
    ))
    session.commit()

    r = client.delete(f"/api/activities/{act.id}")
    assert r.status_code == 204
    assert session.get(Activity, act.id) is None
    # Laps were historically leaked on delete — assert they are gone now.
    assert session.exec(sm_select(Lap).where(Lap.activity_id == act.id)).all() == []
    assert session.exec(sm_select(DataPoint).where(DataPoint.activity_id == act.id)).all() == []

    logs = session.exec(sm_select(EventLog).where(EventLog.category == "delete")).all()
    assert len(logs) == 1
    assert f"deleted activity {act.id}" in logs[0].message


def test_delete_activity_404(client):
    assert client.delete("/api/activities/99999").status_code == 404


def test_patch_activity_shoe_404(client):
    r = client.patch("/api/activities/999/shoe", json={"shoe_id": 1})
    assert r.status_code == 404


def test_patch_activity_shoe_invalid_shoe(client, session):
    act = _make_activity(session)
    r = client.patch(f"/api/activities/{act.id}/shoe", json={"shoe_id": 9999})
    assert r.status_code == 404
