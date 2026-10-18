"""Testes da lógica herdada do curso (is_iss_overhead / is_night) e dos parsers de API."""

from datetime import datetime, timezone

import pytest
import requests

from iss_tracker.api import iss_client


def test_parse_open_notify():
    data = {"timestamp": 1792349132, "message": "success",
            "iss_position": {"longitude": "-57.7563", "latitude": "-27.2336"}}
    parsed = iss_client.parse_open_notify(data)
    assert parsed["latitude"] == pytest.approx(-27.2336)
    assert parsed["longitude"] == pytest.approx(-57.7563)
    assert parsed["source"] == "open-notify"


def test_parse_open_notify_rejects_error():
    with pytest.raises(ValueError):
        iss_client.parse_open_notify({"message": "failure"})


def test_parse_wheretheiss():
    data = {"latitude": -34.18, "longitude": 67.49, "altitude": 426.656,
            "velocity": 27566.93, "timestamp": 1792349134}
    parsed = iss_client.parse_wheretheiss(data)
    assert parsed["altitude_km"] == 426.7
    assert parsed["velocity_kmh"] == 27567


def test_parse_tle_text_and_json():
    text = "ISS (ZARYA)\n1 25544U 98067A   26291.4 ...\n2 25544  51.6327 ...\n"
    name, l1, l2 = iss_client.parse_tle_payload(text)
    assert name == "ISS (ZARYA)" and l1.startswith("1 ") and l2.startswith("2 ")

    js = '{"name": "ISS (ZARYA)", "line1": "1 25544U x", "line2": "2 25544 y"}'
    assert iss_client.parse_tle_payload(js) == ("ISS (ZARYA)", "1 25544U x", "2 25544 y")


@pytest.mark.parametrize(
    "iss_lat, iss_lon, expected",
    [(-23.5, -46.6, True), (-18.6, -46.6, True), (-17.0, -46.6, False), (-23.5, -40.0, False)],
)
def test_is_iss_overhead(iss_lat, iss_lon, expected):
    position = {"latitude": iss_lat, "longitude": iss_lon}
    assert iss_client.is_iss_overhead(-23.5, -46.6, position) is expected


def test_is_night_uses_utc(app, monkeypatch):
    payload = {"results": {"sunrise": "2026-10-18T08:29:27+00:00",
                           "sunset": "2026-10-18T21:13:35+00:00"}}
    monkeypatch.setattr(iss_client, "_get_json", lambda url, **kw: payload)
    with app.app_context():
        assert iss_client.is_night(-23.5, -46.6, datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc))
        assert iss_client.is_night(-23.5, -46.6, datetime(2026, 10, 18, 5, 0, tzinfo=timezone.utc))
        assert not iss_client.is_night(-23.5, -46.6, datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc))


def test_position_falls_back_when_open_notify_fails(app, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"latitude": 1.0, "longitude": 2.0, "altitude": 420.0,
                    "velocity": 27600.0, "timestamp": 1}

    def fake_get(url, **kwargs):
        if "open-notify" in url:
            raise requests.ConnectionError("offline")
        return FakeResponse()

    monkeypatch.setattr(iss_client.requests, "get", fake_get)
    with app.app_context():
        position = iss_client.get_iss_position()
    assert position["source"] == "wheretheiss.at"


def test_position_falls_back_to_tle(app, monkeypatch):
    def offline(url, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(iss_client.requests, "get", offline)
    with app.app_context():
        position = iss_client.get_iss_position()
    assert position["source"] == "tle-sgp4"
    assert -52 <= position["latitude"] <= 52  # inclinação orbital da ISS ≈ 51,6°
    assert 380 <= position["altitude_km"] <= 460
