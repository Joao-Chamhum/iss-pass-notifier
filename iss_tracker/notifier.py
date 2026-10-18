"""
Envio de notificações por e-mail com ``smtplib`` (biblioteca padrão).

As credenciais SMTP vêm do ``.env`` (SMTP_USER / SMTP_PASSWORD). Para Gmail,
use uma *senha de app* (https://myaccount.google.com/apppasswords), nunca a
senha da conta.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from flask import current_app

log = logging.getLogger(__name__)


class EmailNotConfigured(RuntimeError):
    """SMTP_USER/SMTP_PASSWORD não foram definidos."""


def send_email(to_addr: str, subject: str, text: str, html: str | None = None) -> bool:
    """Envia um e-mail. Retorna True em caso de sucesso (ou em modo dry-run)."""
    cfg = current_app.config
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["SMTP_USER"] or "iss-tracker@localhost"
    msg["To"] = to_addr
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if cfg.get("EMAIL_DRY_RUN"):
        log.info("[DRY-RUN] E-mail para %s: %s", to_addr, subject)
        return True

    if not cfg["SMTP_USER"] or not cfg["SMTP_PASSWORD"]:
        raise EmailNotConfigured(
            "Defina SMTP_USER e SMTP_PASSWORD no arquivo .env para enviar e-mails."
        )

    context = ssl.create_default_context()
    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30) as connection:
        connection.starttls(context=context)
        connection.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
        connection.send_message(msg)
    log.info("E-mail enviado para %s: %s", to_addr, subject)
    return True


def _local(iso_utc: str, tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return datetime.fromisoformat(iso_utc).astimezone(tz)


def _wrap_html(title: str, body: str) -> str:
    return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto;
            border:1px solid #dde3ea;border-radius:10px;overflow:hidden">
  <div style="background:#0b1d3a;color:#fff;padding:16px 20px">
    <h2 style="margin:0;font-size:20px">🛰️ {title}</h2>
  </div>
  <div style="padding:20px;color:#1f2937;font-size:15px;line-height:1.5">{body}</div>
  <div style="background:#f3f5f8;color:#6b7280;font-size:12px;padding:10px 20px">
    ISS Pass Notifier · projeto do curso 100 Days of Code (Python)
  </div>
</div>"""


def send_pass_alert(user: dict, iss_pass: dict) -> bool:
    """Aviso antecipado de uma passagem prevista."""
    tz = user.get("timezone") or current_app.config["DEFAULT_TIMEZONE"]
    rise = _local(iss_pass["rise_utc"], tz)
    peak = _local(iss_pass["peak_utc"], tz)
    minutes = max(1, iss_pass["duration_s"] // 60)
    visible = "Sim — céu escuro e ISS iluminada 👀" if iss_pass["visible"] else "Provavelmente não (céu claro ou ISS na sombra)"

    subject = f"🛰️ A ISS vai passar sobre você às {rise:%H:%M}!"
    text = (
        f"Olá, {user['name']}!\n\n"
        f"A Estação Espacial Internacional vai passar sobre sua localização "
        f"({user['latitude']:.4f}, {user['longitude']:.4f}).\n\n"
        f"Início:          {rise:%d/%m/%Y %H:%M:%S} ({tz})\n"
        f"Ponto mais alto: {peak:%H:%M:%S} a {iss_pass['max_elevation']}° de elevação\n"
        f"Duração:         ~{minutes} min\n"
        f"Direção:         de {iss_pass['rise_direction']} para {iss_pass['set_direction']}\n"
        f"Visível a olho nu: {visible}\n\n"
        "Olhe para cima! 👆\n"
    )
    html = _wrap_html("A ISS está chegando!", f"""
      <p>Olá, <b>{user['name']}</b>!</p>
      <p>A Estação Espacial Internacional vai passar sobre sua localização
         (<code>{user['latitude']:.4f}, {user['longitude']:.4f}</code>).</p>
      <table style="border-collapse:collapse;width:100%">
        <tr><td style="padding:4px 0;color:#6b7280">Início</td>
            <td><b>{rise:%d/%m/%Y %H:%M:%S}</b> ({tz})</td></tr>
        <tr><td style="padding:4px 0;color:#6b7280">Ponto mais alto</td>
            <td>{peak:%H:%M:%S} · {iss_pass['max_elevation']}° de elevação</td></tr>
        <tr><td style="padding:4px 0;color:#6b7280">Duração</td><td>~{minutes} min</td></tr>
        <tr><td style="padding:4px 0;color:#6b7280">Direção</td>
            <td>de <b>{iss_pass['rise_direction']}</b> para <b>{iss_pass['set_direction']}</b></td></tr>
        <tr><td style="padding:4px 0;color:#6b7280">Visível a olho nu</td><td>{visible}</td></tr>
      </table>
      <p style="font-size:18px;margin-top:18px">Olhe para cima! 👆</p>""")
    return send_email(user["email"], subject, text, html)


def send_overhead_alert(user: dict, position: dict) -> bool:
    """Aviso 'Look Up' — mesma regra do curso: ISS a ±5° e é noite."""
    subject = "Look Up 👆 A ISS está acima de você!"
    text = (
        f"Olá, {user['name']}!\n\n"
        "The ISS is above you in the sky.\n"
        f"Posição atual da ISS: {position['latitude']:.2f}, {position['longitude']:.2f}\n"
        f"Sua localização:      {user['latitude']:.2f}, {user['longitude']:.2f}\n"
    )
    html = _wrap_html("Look Up 👆", f"""
      <p>Olá, <b>{user['name']}</b>!</p>
      <p><b>The ISS is above you in the sky.</b></p>
      <p>Posição atual da ISS: <code>{position['latitude']:.2f}, {position['longitude']:.2f}</code><br>
         Sua localização: <code>{user['latitude']:.2f}, {user['longitude']:.2f}</code></p>""")
    return send_email(user["email"], subject, text, html)


def send_test_email(to_addr: str) -> bool:
    subject = "✅ ISS Pass Notifier — e-mail de teste"
    text = "Se você recebeu esta mensagem, as notificações por e-mail estão configuradas corretamente."
    html = _wrap_html("Teste de notificação", f"<p>{text}</p>")
    return send_email(to_addr, subject, text, html)
