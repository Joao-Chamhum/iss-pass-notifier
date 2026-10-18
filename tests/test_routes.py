"""Testes das rotas Flask e da persistência em SQLite."""

import iss_tracker.routes as routes

USER = {"name": "Teste", "latitude": -23.55, "longitude": -46.63}


def test_index_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"ISS Pass Notifier" in response.data
    assert b"joaopedrochamhum@gmail.com" in response.data


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}


def test_iss_now(client, fake_position):
    fake_position(latitude=10.0, longitude=20.0)
    data = client.get("/api/iss/now").get_json()
    assert data["latitude"] == 10.0 and data["longitude"] == 20.0


def test_passes_endpoint(client):
    response = client.get("/api/passes?lat=-23.55&lon=-46.63&days=2")
    assert response.status_code == 200
    data = response.get_json()
    assert data["count"] == len(data["passes"])
    assert data["location"] == {"lat": -23.55, "lon": -46.63}


def test_passes_validation(client):
    assert client.get("/api/passes?lat=100&lon=0").status_code == 400
    assert client.get("/api/passes?lat=abc&lon=0").status_code == 400
    assert client.get("/api/passes").status_code == 400


def test_overhead_endpoint(client, fake_position, monkeypatch):
    fake_position(latitude=-22.0, longitude=-45.0)
    monkeypatch.setattr(routes, "is_night", lambda lat, lon: True)
    data = client.get("/api/overhead?lat=-23.55&lon=-46.63").get_json()
    assert data["is_overhead"] is True
    assert data["should_notify"] is True


def test_track_endpoint(client):
    data = client.get("/api/iss/track?before=5&after=5").get_json()
    assert len(data["points"]) == 11


def test_frequency_includes_registered_users(client):
    client.post("/api/users", json=USER)
    data = client.get("/api/stats/frequency?days=1").get_json()
    names = [loc["name"] for loc in data["locations"]]
    assert "São Paulo" in names
    assert "Teste (cadastro)" in names


def test_user_crud_with_default_email(client):
    created = client.post("/api/users", json=USER)
    assert created.status_code == 201
    user = created.get_json()
    assert user["email"] == "joaopedrochamhum@gmail.com"  # destinatário padrão
    assert user["only_dark"] is True and user["active"] is True

    updated = client.patch(f"/api/users/{user['id']}", json={"active": False, "lead_minutes": 30})
    assert updated.get_json()["active"] is False
    assert updated.get_json()["lead_minutes"] == 30

    assert len(client.get("/api/users").get_json()) == 1
    assert client.delete(f"/api/users/{user['id']}").status_code == 204
    assert client.get("/api/users").get_json() == []
    assert client.delete(f"/api/users/{user['id']}").status_code == 404


def test_user_validation(client):
    assert client.post("/api/users", json={**USER, "name": ""}).status_code == 400
    assert client.post("/api/users", json={**USER, "email": "invalido"}).status_code == 400
    assert client.post("/api/users", json={**USER, "latitude": 95}).status_code == 400
    assert client.post("/api/users", json={**USER, "timezone": "Marte/Olympus"}).status_code == 400


def test_notify_test_dry_run(client):
    data = client.post("/api/notify/test", json={}).get_json()
    assert data == {"sent_to": "joaopedrochamhum@gmail.com", "dry_run": True}


def test_notify_test_without_smtp_config(app, client):
    app.config.update(EMAIL_DRY_RUN=False, SMTP_USER="", SMTP_PASSWORD="")
    response = client.post("/api/notify/test", json={})
    assert response.status_code == 503
    assert "SMTP_USER" in response.get_json()["error"]


def test_status(client):
    data = client.get("/api/status").get_json()
    assert data["check_interval_minutes"] == 10
    assert data["notify_email"] == "joaopedrochamhum@gmail.com"
