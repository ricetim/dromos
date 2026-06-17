"""Tests for shoe rename / update via PATCH."""
from app.models import Shoe


def _make_shoe(session, name="Old Name", brand="Nike"):
    shoe = Shoe(name=name, brand=brand)
    session.add(shoe)
    session.commit()
    session.refresh(shoe)
    return shoe


def test_rename_shoe(client, session):
    shoe = _make_shoe(session)
    r = client.patch(f"/api/shoes/{shoe.id}", json={"name": "New Name", "brand": "Saucony"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "New Name"
    assert body["brand"] == "Saucony"
    session.refresh(shoe)
    assert shoe.name == "New Name"
    assert shoe.brand == "Saucony"


def test_rename_shoe_404(client):
    assert client.patch("/api/shoes/9999", json={"name": "X"}).status_code == 404


def test_rename_can_clear_brand(client, session):
    shoe = _make_shoe(session)
    r = client.patch(f"/api/shoes/{shoe.id}", json={"brand": None})
    assert r.status_code == 200
    assert r.json()["brand"] is None
