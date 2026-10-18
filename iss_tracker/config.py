"""
Configuração da aplicação.

Todos os valores sensíveis (usuário/senha SMTP, SECRET_KEY) são lidos de
variáveis de ambiente ou de um arquivo ``.env`` que NÃO é versionado.
Veja ``.env.example`` para a lista completa de variáveis.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega o .env da raiz do projeto (se existir).
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    """Configuração padrão (desenvolvimento/produção)."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")

    # --- Banco de dados (SQLite) -------------------------------------------
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "iss_tracker.db"))

    # --- E-mail (smtplib) ----------------------------------------------------
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = _env_int("SMTP_PORT", 587)
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    # Destinatário padrão das notificações (usado quando o usuário não
    # informa e-mail próprio e no botão "Enviar e-mail de teste").
    NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "joaopedrochamhum@gmail.com")
    # Quando True, os e-mails são apenas registrados no log (útil em testes).
    EMAIL_DRY_RUN = _env_bool("EMAIL_DRY_RUN", False)

    # --- Verificação periódica ---------------------------------------------
    SCHEDULER_ENABLED = _env_bool("SCHEDULER_ENABLED", True)
    CHECK_INTERVAL_MINUTES = _env_int("CHECK_INTERVAL_MINUTES", 10)

    # --- Fontes de dados -----------------------------------------------------
    # Posição em tempo real (mesma API usada no curso).
    ISS_NOW_URL = os.getenv("ISS_NOW_URL", "http://api.open-notify.org/iss-now.json")
    # Fonte alternativa (fallback) com altitude e velocidade.
    ISS_NOW_FALLBACK_URL = os.getenv(
        "ISS_NOW_FALLBACK_URL", "https://api.wheretheiss.at/v1/satellites/25544"
    )
    # Elementos orbitais (TLE) para previsão de passagens.
    TLE_URLS = [
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE",
        "https://tle.ivanstanojevic.me/api/tle/25544",
    ]
    TLE_CACHE_HOURS = _env_int("TLE_CACHE_HOURS", 6)
    SUNRISE_SUNSET_URL = "https://api.sunrise-sunset.org/json"
    HTTP_TIMEOUT = _env_int("HTTP_TIMEOUT", 10)

    # --- Padrões de previsão -------------------------------------------------
    DEFAULT_MIN_ELEVATION = _env_int("DEFAULT_MIN_ELEVATION", 10)
    DEFAULT_LEAD_MINUTES = _env_int("DEFAULT_LEAD_MINUTES", 15)
    DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "America/Sao_Paulo")


class TestConfig(Config):
    """Configuração usada pela suíte de testes."""

    TESTING = True
    SCHEDULER_ENABLED = False
    EMAIL_DRY_RUN = True
    # O caminho do banco é definido pelo fixture do pytest (arquivo temporário).
