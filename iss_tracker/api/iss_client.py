"""
Cliente HTTP para as APIs externas usadas pela aplicação.

* Posição da ISS em tempo real: Open Notify (``iss-now.json``), a mesma API
  utilizada na solução do curso. Os dados de posição são derivados dos
  elementos orbitais publicados pela NASA. Se a Open Notify estiver fora do
  ar, usamos a "Where the ISS at?" como alternativa.
* Elementos orbitais (TLE) da ISS (NORAD 25544): CelesTrak, com fallback.
* Nascer/pôr do sol: sunrise-sunset.org (lógica ``is_night`` do curso).

As funções ``is_iss_overhead`` e ``is_night`` reproduzem a solução original do
curso (ver ``curso/main_original.py``), agora parametrizadas e testáveis.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import current_app

log = logging.getLogger(__name__)

# Margem (em graus) usada no curso para considerar a ISS "acima" do usuário.
OVERHEAD_MARGIN_DEG = 5.0

_tle_lock = threading.Lock()
_tle_cache: dict = {"lines": None, "fetched_at": 0.0, "source": None}


class ISSDataError(RuntimeError):
    """Erro ao obter dados da ISS em todas as fontes disponíveis."""


def _get_json(url: str, **kwargs) -> dict:
    timeout = current_app.config.get("HTTP_TIMEOUT", 10)
    response = requests.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Posição em tempo real
# ---------------------------------------------------------------------------
def parse_open_notify(data: dict) -> dict:
    """Transforma o JSON da Open Notify em um dicionário utilizável."""
    if data.get("message") != "success":
        raise ValueError(f"Resposta inesperada da Open Notify: {data!r}")
    return {
        "latitude": float(data["iss_position"]["latitude"]),
        "longitude": float(data["iss_position"]["longitude"]),
        "timestamp": int(data["timestamp"]),
        "altitude_km": None,
        "velocity_kmh": None,
        "source": "open-notify",
    }


def parse_wheretheiss(data: dict) -> dict:
    """Transforma o JSON da API wheretheiss.at no mesmo formato."""
    return {
        "latitude": float(data["latitude"]),
        "longitude": float(data["longitude"]),
        "timestamp": int(data["timestamp"]),
        "altitude_km": round(float(data["altitude"]), 1),
        "velocity_kmh": round(float(data["velocity"]), 0),
        "source": "wheretheiss.at",
    }


def get_iss_position() -> dict:
    """
    Retorna a posição atual da ISS.

    Ordem de tentativa: Open Notify -> wheretheiss.at -> propagação orbital
    local a partir do TLE (não depende de internet se o TLE estiver em cache).
    """
    cfg = current_app.config
    try:
        return parse_open_notify(_get_json(cfg["ISS_NOW_URL"]))
    except Exception as exc:  # noqa: BLE001 - qualquer falha aciona o fallback
        log.warning("Open Notify indisponível (%s); tentando fallback.", exc)
    try:
        return parse_wheretheiss(_get_json(cfg["ISS_NOW_FALLBACK_URL"]))
    except Exception as exc:  # noqa: BLE001
        log.warning("wheretheiss.at indisponível (%s); usando TLE.", exc)

    from .orbit import position_from_tle  # import tardio evita ciclo

    return position_from_tle()


# ---------------------------------------------------------------------------
# Elementos orbitais (TLE)
# ---------------------------------------------------------------------------
def parse_tle_payload(payload: str) -> tuple[str, str, str]:
    """Aceita o formato texto (CelesTrak) ou JSON (tle.ivanstanojevic.me)."""
    payload = payload.strip()
    if payload.startswith("{"):
        import json

        data = json.loads(payload)
        return data.get("name", "ISS (ZARYA)"), data["line1"].strip(), data["line2"].strip()

    lines = [ln.rstrip() for ln in payload.splitlines() if ln.strip()]
    line1 = next(ln for ln in lines if ln.startswith("1 "))
    line2 = next(ln for ln in lines if ln.startswith("2 "))
    name = lines[0].strip() if not lines[0].startswith("1 ") else "ISS (ZARYA)"
    return name, line1.strip(), line2.strip()


def _tle_file() -> Path:
    return Path(current_app.config["DATABASE_PATH"]).with_name("iss_tle.txt")


def get_tle(force_refresh: bool = False) -> tuple[str, str, str]:
    """Retorna (nome, linha1, linha2) do TLE da ISS, com cache em memória e disco."""
    max_age = current_app.config.get("TLE_CACHE_HOURS", 6) * 3600
    with _tle_lock:
        fresh = time.time() - _tle_cache["fetched_at"] < max_age
        if _tle_cache["lines"] and fresh and not force_refresh:
            return _tle_cache["lines"]

        timeout = current_app.config.get("HTTP_TIMEOUT", 10)
        for url in current_app.config["TLE_URLS"]:
            try:
                resp = requests.get(url, timeout=timeout)
                resp.raise_for_status()
                lines = parse_tle_payload(resp.text)
                _tle_cache.update(lines=lines, fetched_at=time.time(), source=url)
                try:
                    _tle_file().parent.mkdir(parents=True, exist_ok=True)
                    _tle_file().write_text("\n".join(lines), encoding="utf-8")
                except OSError:
                    pass
                return lines
            except Exception as exc:  # noqa: BLE001
                log.warning("Falha ao obter TLE de %s: %s", url, exc)

        if _tle_cache["lines"]:
            log.warning("Usando TLE em cache (possivelmente desatualizado).")
            return _tle_cache["lines"]
        if _tle_file().exists():
            lines = parse_tle_payload(_tle_file().read_text(encoding="utf-8"))
            _tle_cache.update(lines=lines, fetched_at=0.0, source="disk-cache")
            return lines
        raise ISSDataError("Não foi possível obter os elementos orbitais (TLE) da ISS.")


def tle_source() -> str | None:
    return _tle_cache.get("source")


# ---------------------------------------------------------------------------
# Lógica original do curso (Dia 33 - ISS Overhead Notifier)
# ---------------------------------------------------------------------------
def is_iss_overhead(my_lat: float, my_long: float, position: dict | None = None) -> bool:
    """True se a ISS estiver a até ±5° de latitude e longitude do usuário."""
    position = position or get_iss_position()
    iss_lat, iss_long = position["latitude"], position["longitude"]
    return (
        my_lat - OVERHEAD_MARGIN_DEG <= iss_lat <= my_lat + OVERHEAD_MARGIN_DEG
        and my_long - OVERHEAD_MARGIN_DEG <= iss_long <= my_long + OVERHEAD_MARGIN_DEG
    )


def is_night(my_lat: float, my_long: float, now: datetime | None = None) -> bool:
    """
    True se for noite no local informado, via API sunrise-sunset.org.

    Melhoria em relação ao curso: a API devolve horários em UTC, mas o código
    original comparava com ``datetime.now()`` (hora local da máquina). Aqui a
    comparação é feita com datetimes completos em UTC.
    """
    now = now or datetime.now(timezone.utc)
    params = {"lat": my_lat, "lng": my_long, "formatted": 0, "date": now.date().isoformat()}
    data = _get_json(current_app.config["SUNRISE_SUNSET_URL"], params=params)
    sunrise = datetime.fromisoformat(data["results"]["sunrise"])
    sunset = datetime.fromisoformat(data["results"]["sunset"])
    return now >= sunset or now <= sunrise
