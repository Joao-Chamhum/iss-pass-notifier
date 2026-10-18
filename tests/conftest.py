"""Fixtures compartilhadas. Nenhum teste acessa a internet."""

import pytest

from iss_tracker import create_app
from iss_tracker.api import iss_client, orbit
from iss_tracker.config import TestConfig

# TLE real da ISS (época 2026-10-18) — usado para previsões determinísticas.
FIXED_TLE = (
    "ISS (ZARYA)",
    "1 25544U 98067A   26291.46721113  .00007452  00000+0  14361-3 0  9990",
    "2 25544  51.6327  50.0298 0006783 279.2532  80.7689 15.48923373590865",
)


@pytest.fixture(autouse=True)
def fixed_tle(monkeypatch):
    """Evita downloads de TLE e limpa os caches entre testes."""
    monkeypatch.setattr(orbit, "get_tle", lambda *a, **k: FIXED_TLE)
    monkeypatch.setattr(iss_client, "get_tle", lambda *a, **k: FIXED_TLE)
    orbit._pass_cache.clear()
    yield


@pytest.fixture()
def app(tmp_path):
    return create_app(TestConfig, DATABASE_PATH=str(tmp_path / "test.db"))


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def fake_position(monkeypatch):
    """Substitui a posição em tempo real por um valor controlado."""
    position = {"latitude": -23.0, "longitude": -46.0, "timestamp": 1792349132,
                "altitude_km": None, "velocity_kmh": None, "source": "test"}

    def _set(**changes):
        position.update(changes)
        return position

    import iss_tracker.routes as routes
    import iss_tracker.scheduler as scheduler

    monkeypatch.setattr(routes, "get_iss_position", lambda: dict(position))
    monkeypatch.setattr(scheduler, "get_iss_position", lambda: dict(position))
    return _set
