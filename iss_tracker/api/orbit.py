"""
Previsão orbital da ISS com Skyfield (modelo SGP4) a partir do TLE.

Responsável por:
* prever as próximas passagens da ISS sobre uma localização;
* calcular a trajetória (ground track) para desenhar no mapa;
* estimar a posição atual sem internet (fallback);
* estimar a frequência de passagens em diferentes locais (gráfico).

A posição do Sol é calculada com a fórmula de baixa precisão do
Astronomical Almanac (erro < 0,01°), suficiente para decidir se o céu está
escuro e se a ISS está iluminada — sem baixar efemérides.
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timedelta, timezone

from skyfield.api import EarthSatellite, load, wgs84

from .iss_client import get_tle

EARTH_RADIUS_KM = 6378.137
# Sol abaixo de -6° = fim do crepúsculo civil (céu escuro o bastante).
DARK_SUN_ELEVATION = -6.0

_ts = load.timescale()  # usa dados embutidos, não faz download
_cache_lock = threading.Lock()
_pass_cache: dict = {}
PASS_CACHE_SECONDS = 15 * 60

COMPASS_PT = ["N", "NNE", "NE", "ENE", "L", "ESE", "SE", "SSE",
              "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def get_satellite() -> EarthSatellite:
    name, line1, line2 = get_tle()
    return EarthSatellite(line1, line2, name, _ts)


def azimuth_to_compass(azimuth_deg: float) -> str:
    """Converte azimute (graus) em direção cardeal em português."""
    return COMPASS_PT[int((azimuth_deg % 360) / 22.5 + 0.5) % 16]


def _julian_day(dt: datetime) -> float:
    return dt.timestamp() / 86400.0 + 2440587.5


def sun_unit_vector(dt: datetime) -> tuple[float, float, float]:
    """Vetor unitário Terra->Sol no referencial equatorial (≈ GCRS)."""
    n = _julian_day(dt) - 2451545.0
    mean_long = math.radians((280.460 + 0.9856474 * n) % 360)
    mean_anom = math.radians((357.528 + 0.9856003 * n) % 360)
    ecl_long = mean_long + math.radians(1.915) * math.sin(mean_anom) \
        + math.radians(0.020) * math.sin(2 * mean_anom)
    obliquity = math.radians(23.439 - 0.0000004 * n)
    return (
        math.cos(ecl_long),
        math.cos(obliquity) * math.sin(ecl_long),
        math.sin(obliquity) * math.sin(ecl_long),
    )


def sun_elevation(lat: float, lon: float, dt: datetime) -> float:
    """Elevação aproximada do Sol (graus) vista do ponto (lat, lon) no instante dt."""
    x, y, z = sun_unit_vector(dt)
    ra = math.atan2(y, x)
    dec = math.asin(z)
    n = _julian_day(dt) - 2451545.0
    gmst = math.radians((280.46061837 + 360.98564736629 * n) % 360)
    hour_angle = gmst + math.radians(lon) - ra
    phi = math.radians(lat)
    sin_el = math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))


def is_sunlit(position_km, dt: datetime) -> bool:
    """Modelo de sombra cilíndrica: a ISS está iluminada pelo Sol?"""
    sx, sy, sz = sun_unit_vector(dt)
    px, py, pz = (float(v) for v in position_km)
    along = px * sx + py * sy + pz * sz
    if along > 0:
        return True
    perp = math.sqrt(max(0.0, px * px + py * py + pz * pz - along * along))
    return perp > EARTH_RADIUS_KM


# ---------------------------------------------------------------------------
# Posição e trajetória
# ---------------------------------------------------------------------------
def position_from_tle(when: datetime | None = None) -> dict:
    when = when or datetime.now(timezone.utc)
    sat = get_satellite()
    geocentric = sat.at(_ts.from_datetime(when))
    sub = wgs84.subpoint_of(geocentric)
    height = wgs84.height_of(geocentric).km
    speed_kmh = float(math.sqrt(sum(v * v for v in geocentric.velocity.km_per_s))) * 3600
    return {
        "latitude": round(float(sub.latitude.degrees), 4),
        "longitude": round(float(sub.longitude.degrees), 4),
        "timestamp": int(when.timestamp()),
        "altitude_km": round(float(height), 1),
        "velocity_kmh": round(speed_kmh, 0),
        "source": "tle-sgp4",
    }


def ground_track(minutes_before: int = 45, minutes_after: int = 90, step_s: int = 60) -> list[dict]:
    """Pontos (lat, lon) da trajetória da ISS ao redor do instante atual."""
    sat = get_satellite()
    now = datetime.now(timezone.utc)
    points = []
    for offset in range(-minutes_before * 60, minutes_after * 60 + 1, step_s):
        t = now + timedelta(seconds=offset)
        sub = wgs84.subpoint_of(sat.at(_ts.from_datetime(t)))
        points.append({
            "lat": round(float(sub.latitude.degrees), 3),
            "lon": round(float(sub.longitude.degrees), 3),
            "t": int(t.timestamp()),
            "future": offset >= 0,
        })
    return points


# ---------------------------------------------------------------------------
# Previsão de passagens
# ---------------------------------------------------------------------------
def predict_passes(
    lat: float,
    lon: float,
    days: float = 3,
    min_elevation: float = 10,
    start: datetime | None = None,
    satellite: EarthSatellite | None = None,
) -> list[dict]:
    """
    Lista as passagens da ISS sobre (lat, lon) nos próximos ``days`` dias.

    Cada passagem contém início/culminação/fim (UTC, ISO 8601), elevação
    máxima, duração, direções de entrada/saída e se é visível a olho nu
    (céu escuro no observador e ISS iluminada pelo Sol).
    """
    sat = satellite or get_satellite()
    start = start or datetime.now(timezone.utc)
    observer = wgs84.latlon(lat, lon)
    t0 = _ts.from_datetime(start)
    t1 = _ts.from_datetime(start + timedelta(days=days))
    times, events = sat.find_events(observer, t0, t1, altitude_degrees=min_elevation)

    difference = sat - observer
    passes, current = [], None
    for t, event in zip(times, events):
        dt = t.utc_datetime()
        alt, az, _ = difference.at(t).altaz()
        point = {"time": dt, "elevation": float(alt.degrees), "azimuth": float(az.degrees)}
        if event == 0:  # nasce acima de min_elevation
            current = {"rise": point, "peak": point, "samples": [(t, dt)]}
        elif current is None:
            continue  # passagem já em andamento no início da janela: ignorada
        elif event == 1:  # culminação
            if point["elevation"] >= current["peak"]["elevation"]:
                current["peak"] = point
            current["samples"].append((t, dt))
        elif event == 2:  # se põe
            current["set"] = point
            current["samples"].append((t, dt))
            passes.append(_format_pass(sat, lat, lon, current))
            current = None
    return passes


def _format_pass(sat: EarthSatellite, lat: float, lon: float, raw: dict) -> dict:
    rise, peak, set_ = raw["rise"], raw["peak"], raw["set"]
    sun_el = sun_elevation(lat, lon, peak["time"])
    dark = sun_el <= DARK_SUN_ELEVATION
    sunlit = any(is_sunlit(sat.at(t).position.km, dt) for t, dt in raw["samples"])
    return {
        "rise_utc": rise["time"].isoformat(timespec="seconds"),
        "peak_utc": peak["time"].isoformat(timespec="seconds"),
        "set_utc": set_["time"].isoformat(timespec="seconds"),
        "duration_s": int((set_["time"] - rise["time"]).total_seconds()),
        "max_elevation": round(peak["elevation"], 1),
        "rise_direction": azimuth_to_compass(rise["azimuth"]),
        "set_direction": azimuth_to_compass(set_["azimuth"]),
        "rise_azimuth": round(rise["azimuth"], 1),
        "set_azimuth": round(set_["azimuth"], 1),
        "sun_elevation": round(sun_el, 1),
        "dark_sky": dark,
        "iss_sunlit": sunlit,
        "visible": dark and sunlit,
    }


def predict_passes_cached(lat: float, lon: float, days: float = 3, min_elevation: float = 10) -> list[dict]:
    """Mesma coisa que ``predict_passes``, com cache de 15 minutos."""
    key = (round(lat, 2), round(lon, 2), days, min_elevation)
    now = time.time()
    with _cache_lock:
        hit = _pass_cache.get(key)
        if hit and now - hit[0] < PASS_CACHE_SECONDS:
            return hit[1]
    result = predict_passes(lat, lon, days=days, min_elevation=min_elevation)
    with _cache_lock:
        _pass_cache[key] = (now, result)
    return result


def pass_frequency(locations: list[dict], days: int = 7, min_elevation: float = 10) -> list[dict]:
    """Conta passagens (totais e visíveis) para cada local informado."""
    sat = get_satellite()
    start = datetime.now(timezone.utc)
    results = []
    for loc in locations:
        passes = predict_passes(loc["lat"], loc["lon"], days=days, min_elevation=min_elevation,
                                start=start, satellite=sat)
        results.append({
            "name": loc["name"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "total": len(passes),
            "visible": sum(1 for p in passes if p["visible"]),
            "best_elevation": max((p["max_elevation"] for p in passes), default=0),
        })
    return results
