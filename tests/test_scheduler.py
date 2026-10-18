"""Testes da verificação periódica e do envio de notificações (smtplib simulado)."""

from datetime import datetime, timedelta, timezone

import pytest

import iss_tracker.scheduler as scheduler
from iss_tracker import database as db
from iss_tracker import notifier


def make_pass(rise: datetime, visible: bool = True) -> dict:
    return {
        "rise_utc": rise.isoformat(timespec="seconds"),
        "peak_utc": (rise + timedelta(minutes=3)).isoformat(timespec="seconds"),
        "set_utc": (rise + timedelta(minutes=6)).isoformat(timespec="seconds"),
        "duration_s": 360, "max_elevation": 54.2,
        "rise_direction": "NO", "set_direction": "SE",
        "rise_azimuth": 315.0, "set_azimuth": 135.0, "sun_elevation": -20.0,
        "dark_sky": visible, "iss_sunlit": visible, "visible": visible,
    }


@pytest.fixture()
def sent(monkeypatch):
    """Captura os e-mails em vez de enviá-los."""
    outbox = []
    monkeypatch.setattr(notifier, "send_email",
                        lambda to, subject, text, html=None: outbox.append((to, subject, text)) or True)
    return outbox


@pytest.fixture()
def user(app):
    with app.app_context():
        return db.create_user({
            "name": "João", "email": "joaopedrochamhum@gmail.com",
            "latitude": -23.55, "longitude": -46.63, "timezone": "America/Sao_Paulo",
            "min_elevation": 10, "lead_minutes": 15, "only_dark": 1,
            "notify_passes": 1, "notify_overhead": 0, "active": 1,
        })


def test_pass_alert_sent_once(app, user, sent, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(scheduler, "predict_passes",
                        lambda *a, **k: [make_pass(now + timedelta(minutes=8))])

    first = scheduler.run_check(app)
    assert len(first["sent"]) == 1
    assert sent[0][0] == "joaopedrochamhum@gmail.com"
    assert "ISS" in sent[0][1]

    second = scheduler.run_check(app)  # mesma passagem -> sem duplicar
    assert second["sent"] == []
    assert len(sent) == 1

    with app.app_context():
        history = db.recent_notifications()
    assert history[0]["kind"] == "pass"


def test_pass_outside_window_is_ignored(app, user, sent, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(scheduler, "predict_passes",
                        lambda *a, **k: [make_pass(now + timedelta(hours=3))])
    assert scheduler.run_check(app)["sent"] == []
    assert sent == []


def test_invisible_pass_respects_only_dark(app, user, sent, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(scheduler, "predict_passes",
                        lambda *a, **k: [make_pass(now + timedelta(minutes=5), visible=False)])
    assert scheduler.run_check(app)["sent"] == []

    with app.app_context():
        db.update_user(user["id"], {"only_dark": 0})
    assert len(scheduler.run_check(app)["sent"]) == 1


def test_overhead_alert_course_rule(app, user, sent, monkeypatch, fake_position):
    with app.app_context():
        db.update_user(user["id"], {"notify_passes": 0, "notify_overhead": 1})
    fake_position(latitude=-21.0, longitude=-44.0)  # dentro de ±5°
    monkeypatch.setattr(scheduler, "is_night", lambda lat, lon, now=None: True)

    result = scheduler.run_check(app)
    assert [s["event"].split(":")[0] for s in result["sent"]] == ["overhead"]
    assert "Look Up" in sent[0][1]


def test_inactive_users_are_skipped(app, user, sent, monkeypatch):
    with app.app_context():
        db.update_user(user["id"], {"active": 0})
    monkeypatch.setattr(scheduler, "predict_passes",
                        lambda *a, **k: [make_pass(datetime.now(timezone.utc) + timedelta(minutes=5))])
    assert scheduler.run_check(app)["users"] == 0
    assert sent == []


def test_smtp_flow(app, monkeypatch):
    """Garante que o smtplib é chamado com STARTTLS + login + envio."""
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user))

        def send_message(self, msg):
            calls.append(("send", msg["To"], msg["Subject"]))

    monkeypatch.setattr(notifier.smtplib, "SMTP", FakeSMTP)
    app.config.update(EMAIL_DRY_RUN=False, SMTP_USER="remetente@gmail.com", SMTP_PASSWORD="app-pass")
    with app.app_context():
        notifier.send_test_email("joaopedrochamhum@gmail.com")

    assert calls[0] == ("connect", "smtp.gmail.com", 587)
    assert ("starttls",) in calls
    assert ("login", "remetente@gmail.com") in calls
    assert calls[-1][0:2] == ("send", "joaopedrochamhum@gmail.com")
