"""
Rotas HTTP da aplicação (Blueprint).

Página:
    GET  /                       -> dashboard

API REST (JSON):
    GET  /api/iss/now            -> posição atual da ISS
    GET  /api/iss/track          -> trajetória (ground track) para o mapa
    GET  /api/passes             -> próximas passagens sobre lat/lon
    GET  /api/overhead           -> verificação do curso (ISS acima + noite)
    GET  /api/stats/frequency    -> nº de passagens por local (gráfico)
    GET  /api/users              -> lista usuários cadastrados
    POST /api/users              -> cadastra usuário
    PATCH  /api/users/<id>       -> atualiza preferências
    DELETE /api/users/<id>       -> remove usuário
    GET  /api/notifications      -> histórico de e-mails enviados
    POST /api/notify/test        -> envia e-mail de teste
    POST /api/check              -> executa a verificação periódica agora
    GET  /api/status             -> status do agendador/configuração
"""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, render_template, request

from . import database as db
from . import notifier
from .api import (
    ISSDataError,
    get_iss_position,
    ground_track,
    is_iss_overhead,
    is_night,
    pass_frequency,
    predict_passes_cached,
)
from .api.iss_client import tle_source
from .scheduler import next_run, run_check

bp = Blueprint("main", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Locais de referência para o gráfico de frequência de passagens.
REFERENCE_LOCATIONS = [
    {"name": "Manaus", "lat": -3.1190, "lon": -60.0217},
    {"name": "Brasília", "lat": -15.7939, "lon": -47.8828},
    {"name": "São José dos Campos", "lat": -23.1896, "lon": -45.8841},
    {"name": "São Paulo", "lat": -23.5505, "lon": -46.6333},
    {"name": "Porto Alegre", "lat": -30.0346, "lon": -51.2177},
    {"name": "Houston (NASA JSC)", "lat": 29.5593, "lon": -95.0900},
    {"name": "Londres", "lat": 51.5074, "lon": -0.1278},
    {"name": "Oslo", "lat": 59.9139, "lon": 10.7522},
]


class ValidationError(ValueError):
    pass


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


@bp.errorhandler(ValidationError)
def _handle_validation(exc):
    return _error(str(exc), 400)


@bp.errorhandler(ISSDataError)
def _handle_iss_error(exc):
    return _error(str(exc), 503)


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------
def _float(value, name: str, lo: float, hi: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"'{name}' deve ser numérico.") from None
    if not lo <= number <= hi:
        raise ValidationError(f"'{name}' deve estar entre {lo} e {hi}.")
    return number


def _int(value, name: str, lo: int, hi: int) -> int:
    return int(round(_float(value, name, lo, hi)))


def _coords_from_query() -> tuple[float, float]:
    lat = _float(request.args.get("lat"), "lat", -90, 90)
    lon = _float(request.args.get("lon"), "lon", -180, 180)
    return lat, lon


def validate_user_payload(data: dict, partial: bool = False) -> dict:
    cfg = current_app.config
    clean: dict = {}

    if "name" in data or not partial:
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValidationError("Informe o nome.")
        clean["name"] = name[:80]

    if "email" in data or not partial:
        email = str(data.get("email") or cfg["NOTIFY_EMAIL"]).strip()
        if not EMAIL_RE.match(email):
            raise ValidationError("E-mail inválido.")
        clean["email"] = email

    if "latitude" in data or not partial:
        clean["latitude"] = _float(data.get("latitude"), "latitude", -90, 90)
    if "longitude" in data or not partial:
        clean["longitude"] = _float(data.get("longitude"), "longitude", -180, 180)

    if "timezone" in data or not partial:
        tz = str(data.get("timezone") or cfg["DEFAULT_TIMEZONE"])
        try:
            ZoneInfo(tz)
        except Exception:  # noqa: BLE001
            raise ValidationError(f"Fuso horário inválido: {tz}") from None
        clean["timezone"] = tz

    if "min_elevation" in data or not partial:
        clean["min_elevation"] = _int(data.get("min_elevation", cfg["DEFAULT_MIN_ELEVATION"]),
                                      "min_elevation", 0, 80)
    if "lead_minutes" in data or not partial:
        clean["lead_minutes"] = _int(data.get("lead_minutes", cfg["DEFAULT_LEAD_MINUTES"]),
                                     "lead_minutes", 1, 180)

    defaults = {"only_dark": True, "notify_passes": True, "notify_overhead": True, "active": True}
    for key, default in defaults.items():
        if key in data or not partial:
            clean[key] = 1 if bool(data.get(key, default)) else 0
    return clean


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------
@bp.get("/")
def index():
    cfg = current_app.config
    return render_template(
        "index.html",
        default_email=cfg["NOTIFY_EMAIL"],
        default_timezone=cfg["DEFAULT_TIMEZONE"],
        default_min_elevation=cfg["DEFAULT_MIN_ELEVATION"],
        default_lead_minutes=cfg["DEFAULT_LEAD_MINUTES"],
        check_interval=cfg["CHECK_INTERVAL_MINUTES"],
    )


# ---------------------------------------------------------------------------
# Dados da ISS
# ---------------------------------------------------------------------------
@bp.get("/api/iss/now")
def iss_now():
    position = get_iss_position()
    if position.get("altitude_km") is None:
        # A Open Notify só informa lat/lon; completamos altitude e velocidade
        # com a propagação orbital (SGP4) do TLE.
        try:
            from datetime import datetime, timezone

            from .api.orbit import position_from_tle

            when = datetime.fromtimestamp(position["timestamp"], timezone.utc)
            extra = position_from_tle(when)
            position["altitude_km"] = extra["altitude_km"]
            position["velocity_kmh"] = extra["velocity_kmh"]
        except Exception:  # noqa: BLE001 - dado complementar, não essencial
            pass
    return jsonify(position)


@bp.get("/api/iss/track")
def iss_track():
    before = _int(request.args.get("before", 45), "before", 0, 180)
    after = _int(request.args.get("after", 90), "after", 0, 360)
    return jsonify({"points": ground_track(before, after)})


@bp.get("/api/passes")
def passes():
    lat, lon = _coords_from_query()
    days = _int(request.args.get("days", 3), "days", 1, 10)
    min_el = _int(request.args.get("min_elevation", current_app.config["DEFAULT_MIN_ELEVATION"]),
                  "min_elevation", 0, 80)
    result = predict_passes_cached(lat, lon, days=days, min_elevation=min_el)
    return jsonify({
        "location": {"lat": lat, "lon": lon},
        "days": days,
        "min_elevation": min_el,
        "count": len(result),
        "visible_count": sum(1 for p in result if p["visible"]),
        "tle_source": tle_source(),
        "passes": result,
    })


@bp.get("/api/overhead")
def overhead():
    """Executa a lógica original do curso para a localização informada."""
    lat, lon = _coords_from_query()
    position = get_iss_position()
    above = is_iss_overhead(lat, lon, position)
    try:
        night = is_night(lat, lon)
    except Exception:  # noqa: BLE001 - API externa indisponível
        night = None
    return jsonify({
        "iss_position": position,
        "is_overhead": above,
        "is_night": night,
        "should_notify": bool(above and night),
        "margin_deg": 5,
    })


@bp.get("/api/stats/frequency")
def frequency():
    days = _int(request.args.get("days", 7), "days", 1, 10)
    min_el = _int(request.args.get("min_elevation", current_app.config["DEFAULT_MIN_ELEVATION"]),
                  "min_elevation", 0, 80)
    locations = list(REFERENCE_LOCATIONS)
    for user in db.list_users():
        locations.append({"name": f"{user['name']} (cadastro)", "lat": user["latitude"],
                          "lon": user["longitude"]})
    if "lat" in request.args and "lon" in request.args:
        lat, lon = _coords_from_query()
        locations.append({"name": "Local selecionado", "lat": lat, "lon": lon})
    return jsonify({"days": days, "min_elevation": min_el,
                    "locations": pass_frequency(locations, days=days, min_elevation=min_el)})


# ---------------------------------------------------------------------------
# Usuários (SQLite)
# ---------------------------------------------------------------------------
@bp.get("/api/users")
def users_list():
    return jsonify(db.list_users())


@bp.post("/api/users")
def users_create():
    data = validate_user_payload(request.get_json(silent=True) or {})
    return jsonify(db.create_user(data)), 201


@bp.patch("/api/users/<int:user_id>")
def users_update(user_id: int):
    if not db.get_user(user_id):
        return _error("Usuário não encontrado.", 404)
    data = validate_user_payload(request.get_json(silent=True) or {}, partial=True)
    return jsonify(db.update_user(user_id, data))


@bp.delete("/api/users/<int:user_id>")
def users_delete(user_id: int):
    if not db.delete_user(user_id):
        return _error("Usuário não encontrado.", 404)
    return "", 204


@bp.get("/api/notifications")
def notifications():
    return jsonify(db.recent_notifications())


# ---------------------------------------------------------------------------
# Notificações / operação
# ---------------------------------------------------------------------------
@bp.post("/api/notify/test")
def notify_test():
    payload = request.get_json(silent=True) or {}
    to_addr = str(payload.get("email") or current_app.config["NOTIFY_EMAIL"]).strip()
    if not EMAIL_RE.match(to_addr):
        raise ValidationError("E-mail inválido.")
    try:
        notifier.send_test_email(to_addr)
    except notifier.EmailNotConfigured as exc:
        return _error(str(exc), 503)
    except Exception as exc:  # noqa: BLE001
        return _error(f"Falha ao enviar e-mail: {exc}", 502)
    return jsonify({"sent_to": to_addr, "dry_run": bool(current_app.config["EMAIL_DRY_RUN"])})


@bp.post("/api/check")
def check_now():
    return jsonify(run_check(current_app._get_current_object()))


@bp.get("/api/status")
def status():
    cfg = current_app.config
    return jsonify({
        "scheduler_enabled": cfg["SCHEDULER_ENABLED"],
        "check_interval_minutes": cfg["CHECK_INTERVAL_MINUTES"],
        "next_check": next_run(),
        "email_configured": bool(cfg["SMTP_USER"] and cfg["SMTP_PASSWORD"]),
        "email_dry_run": cfg["EMAIL_DRY_RUN"],
        "notify_email": cfg["NOTIFY_EMAIL"],
        "users": len(db.list_users()),
    })


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})
