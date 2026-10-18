"""
Camada de persistência em SQLite (biblioteca padrão ``sqlite3``).

Tabelas:
    users          -> localização e preferências de notificação de cada usuário
    notifications  -> histórico de e-mails enviados (evita notificações duplicadas)
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import click
from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    email            TEXT    NOT NULL,
    latitude         REAL    NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude        REAL    NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    timezone         TEXT    NOT NULL DEFAULT 'America/Sao_Paulo',
    min_elevation    INTEGER NOT NULL DEFAULT 10,
    lead_minutes     INTEGER NOT NULL DEFAULT 15,
    only_dark        INTEGER NOT NULL DEFAULT 1,   -- só passagens com céu escuro
    notify_passes    INTEGER NOT NULL DEFAULT 1,   -- aviso antecipado (previsão orbital)
    notify_overhead  INTEGER NOT NULL DEFAULT 1,   -- aviso "olhe para cima" (lógica do curso)
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL,          -- 'pass' | 'overhead' | 'test'
    event_key  TEXT    NOT NULL,          -- identifica a passagem/evento notificado
    sent_at    TEXT    NOT NULL,
    UNIQUE (user_id, kind, event_key)
);
"""

USER_FIELDS = (
    "name", "email", "latitude", "longitude", "timezone", "min_elevation",
    "lead_minutes", "only_dark", "notify_passes", "notify_overhead", "active",
)


def _connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    """Retorna a conexão do contexto atual (uma por requisição/tarefa)."""
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    get_db().executescript(SCHEMA)
    get_db().commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------
def row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    for key in ("only_dark", "notify_passes", "notify_overhead", "active"):
        if key in data:
            data[key] = bool(data[key])
    return data


def list_users(only_active: bool = False) -> list[dict]:
    sql = "SELECT * FROM users"
    if only_active:
        sql += " WHERE active = 1"
    sql += " ORDER BY id"
    return [row_to_dict(r) for r in get_db().execute(sql).fetchall()]


def get_user(user_id: int) -> dict | None:
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return row_to_dict(row) if row else None


def create_user(data: dict) -> dict:
    values = {k: data[k] for k in USER_FIELDS if k in data}
    values["created_at"] = _now_iso()
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    db = get_db()
    cur = db.execute(f"INSERT INTO users ({cols}) VALUES ({marks})", tuple(values.values()))
    db.commit()
    return get_user(cur.lastrowid)


def update_user(user_id: int, data: dict) -> dict | None:
    values = {k: data[k] for k in USER_FIELDS if k in data}
    if values:
        assignments = ", ".join(f"{k} = ?" for k in values)
        db = get_db()
        db.execute(f"UPDATE users SET {assignments} WHERE id = ?", (*values.values(), user_id))
        db.commit()
    return get_user(user_id)


def delete_user(user_id: int) -> bool:
    db = get_db()
    cur = db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Histórico de notificações
# ---------------------------------------------------------------------------
def was_notified(user_id: int, kind: str, event_key: str) -> bool:
    row = get_db().execute(
        "SELECT 1 FROM notifications WHERE user_id = ? AND kind = ? AND event_key = ?",
        (user_id, kind, event_key),
    ).fetchone()
    return row is not None


def record_notification(user_id: int, kind: str, event_key: str) -> None:
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO notifications (user_id, kind, event_key, sent_at) VALUES (?, ?, ?, ?)",
        (user_id, kind, event_key, _now_iso()),
    )
    db.commit()


def recent_notifications(limit: int = 20) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT n.id, n.kind, n.event_key, n.sent_at, u.name, u.email
        FROM notifications n JOIN users u ON u.id = n.user_id
        ORDER BY n.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Integração com o Flask
# ---------------------------------------------------------------------------
@click.command("init-db")
def init_db_command() -> None:
    """Cria as tabelas do banco de dados (comando: ``flask --app run init-db``)."""
    init_db()
    click.echo("Banco de dados inicializado.")


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    with app.app_context():
        init_db()
