"""Testes da previsão orbital (Skyfield/SGP4) e dos cálculos solares."""

from datetime import datetime, timezone

import pytest

from iss_tracker.api import orbit

START = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
SAO_PAULO = (-23.5505, -46.6333)


def test_predict_passes_structure():
    passes = orbit.predict_passes(*SAO_PAULO, days=3, min_elevation=10, start=START)
    assert len(passes) >= 5  # a ISS passa várias vezes por dia em latitudes médias
    for p in passes:
        rise = datetime.fromisoformat(p["rise_utc"])
        peak = datetime.fromisoformat(p["peak_utc"])
        set_ = datetime.fromisoformat(p["set_utc"])
        assert rise <= peak <= set_
        assert 0 < p["duration_s"] < 15 * 60
        assert 10 <= p["max_elevation"] <= 90
        assert p["visible"] == (p["dark_sky"] and p["iss_sunlit"])


def test_higher_min_elevation_gives_fewer_passes():
    low = orbit.predict_passes(*SAO_PAULO, days=3, min_elevation=10, start=START)
    high = orbit.predict_passes(*SAO_PAULO, days=3, min_elevation=40, start=START)
    assert len(high) < len(low)


def test_no_passes_near_pole():
    # A inclinação de 51,6° impede passagens altas sobre o Polo Sul.
    assert orbit.predict_passes(-89.0, 0.0, days=2, min_elevation=10, start=START) == []


@pytest.mark.parametrize("az, expected", [(0, "N"), (44, "NE"), (90, "L"), (180, "S"),
                                          (225, "SO"), (270, "O"), (359, "N")])
def test_azimuth_to_compass(az, expected):
    assert orbit.azimuth_to_compass(az) == expected


def test_sun_elevation_sanity():
    # Meio-dia solar em São Paulo (≈14:51 UTC em 18/10/2026): Sol alto.
    assert orbit.sun_elevation(-23.5, -46.6, datetime(2026, 10, 18, 14, 51, tzinfo=timezone.utc)) > 70
    # Madrugada: Sol bem abaixo do horizonte.
    assert orbit.sun_elevation(-23.5, -46.6, datetime(2026, 10, 18, 5, 0, tzinfo=timezone.utc)) < -30


def test_is_sunlit_shadow_model():
    when = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    sx, sy, sz = orbit.sun_unit_vector(when)
    r = orbit.EARTH_RADIUS_KM + 420
    assert orbit.is_sunlit((sx * r, sy * r, sz * r), when)          # lado do Sol
    assert not orbit.is_sunlit((-sx * r, -sy * r, -sz * r), when)   # atrás da Terra


def test_ground_track_points():
    points = orbit.ground_track(10, 20)
    assert len(points) == 31
    assert all(-52 <= p["lat"] <= 52 for p in points)
    assert points[0]["future"] is False and points[-1]["future"] is True


def test_pass_frequency():
    result = orbit.pass_frequency([{"name": "SP", "lat": -23.55, "lon": -46.63}], days=2)
    assert result[0]["name"] == "SP"
    assert result[0]["total"] >= result[0]["visible"] >= 0
