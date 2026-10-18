"""
Verificação periódica (padrão: a cada 10 minutos) com APScheduler.

A cada execução, para cada usuário ativo:
1. **Aviso antecipado** — prevê as passagens das próximas horas e envia um
   e-mail quando uma passagem começa dentro da janela de antecedência
   configurada (``lead_minutes``).
2. **Aviso "Look Up"** (lógica do curso) — se a ISS estiver a ±5° da
   localização do usuário e for noite, envia o e-mail clássico do curso.

O histórico em ``notifications`` impede e-mails duplicados para o mesmo evento.
"""

from __future__ import annotations

import atexit
import logging
import os
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from . import database as db
from . import notifier
from .api import get_iss_position, is_iss_overhead, is_night, predict_passes

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _pass_is_wanted(user: dict, iss_pass: dict) -> bool:
    return iss_pass["visible"] if user["only_dark"] else True


def check_user(user: dict, now: datetime, interval_min: int, position: dict | None) -> list[str]:
    """Executa as verificações de um usuário e devolve a lista de e-mails enviados."""
    sent: list[str] = []

    if user["notify_passes"]:
        window = timedelta(minutes=max(user["lead_minutes"], interval_min))
        passes = predict_passes(user["latitude"], user["longitude"], days=1,
                                min_elevation=user["min_elevation"], start=now)
        for iss_pass in passes:
            rise = datetime.fromisoformat(iss_pass["rise_utc"])
            if not (now <= rise <= now + window) or not _pass_is_wanted(user, iss_pass):
                continue
            key = iss_pass["rise_utc"][:16]  # AAAA-MM-DDTHH:MM
            if db.was_notified(user["id"], "pass", key):
                continue
            notifier.send_pass_alert(user, iss_pass)
            db.record_notification(user["id"], "pass", key)
            sent.append(f"pass:{key}")

    if user["notify_overhead"] and position is not None:
        if is_iss_overhead(user["latitude"], user["longitude"], position) and \
                is_night(user["latitude"], user["longitude"], now):
            key = now.strftime("%Y-%m-%dT%H")  # no máximo um aviso por hora
            if not db.was_notified(user["id"], "overhead", key):
                notifier.send_overhead_alert(user, position)
                db.record_notification(user["id"], "overhead", key)
                sent.append(f"overhead:{key}")
    return sent


def run_check(app) -> dict:
    """Roda uma rodada completa de verificação (também usada pela rota /api/check)."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        interval = app.config["CHECK_INTERVAL_MINUTES"]
        users = db.list_users(only_active=True)
        summary = {"checked_at": now.isoformat(timespec="seconds"), "users": len(users),
                   "sent": [], "errors": []}
        if not users:
            return summary

        position = None
        if any(u["notify_overhead"] for u in users):
            try:
                position = get_iss_position()
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"posição da ISS: {exc}")

        for user in users:
            try:
                for item in check_user(user, now, interval, position):
                    summary["sent"].append({"user_id": user["id"], "event": item})
            except Exception as exc:  # noqa: BLE001 - um usuário não derruba os demais
                log.exception("Falha ao verificar usuário %s", user["id"])
                summary["errors"].append(f"usuário {user['id']}: {exc}")
        log.info("Verificação concluída: %s", summary)
        return summary


def start_scheduler(app) -> BackgroundScheduler | None:
    """Inicia o agendador em segundo plano (uma única vez por processo)."""
    global _scheduler
    if not app.config.get("SCHEDULER_ENABLED") or _scheduler is not None:
        return _scheduler
    # Com `flask run --debug` (reloader ativo), só o processo filho deve agendar.
    from_cli = os.environ.get("FLASK_RUN_FROM_CLI") == "true"
    if from_cli and app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return None

    interval = app.config["CHECK_INTERVAL_MINUTES"]
    _scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    _scheduler.add_job(
        run_check, "interval", minutes=interval, args=[app], id="iss-check",
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
        max_instances=1, coalesce=True,
    )
    _scheduler.start()
    atexit.register(lambda: _scheduler.shutdown(wait=False) if _scheduler else None)
    log.info("Agendador iniciado: verificação a cada %s minutos.", interval)
    return _scheduler


def next_run() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("iss-check")
    return job.next_run_time.isoformat(timespec="seconds") if job and job.next_run_time else None
