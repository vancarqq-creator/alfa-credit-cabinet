"""Слой данных: SQLite (WAL) + оптимистичная блокировка. Схема совместима с переносом на PostgreSQL."""
import json, os, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "data/credit.db")
JSON_COLS = ("company", "financials", "documents", "checks", "scoring", "decision", "offer", "info_request")
COLS = ("status", "product", "amount", "term_months", "purpose", "consent", *JSON_COLS, "updated_at")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, pwd_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('client','underwriter')), name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications(
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, product TEXT, amount REAL, term_months INTEGER, purpose TEXT,
  consent INTEGER NOT NULL DEFAULT 0, company TEXT, financials TEXT, documents TEXT, checks TEXT,
  scoring TEXT, decision TEXT, offer TEXT, info_request TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_app_user ON applications(user_id);
CREATE INDEX IF NOT EXISTS ix_app_status ON applications(status);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, app_id TEXT NOT NULL REFERENCES applications(id),
  ts TEXT NOT NULL, actor TEXT NOT NULL, from_status TEXT, to_status TEXT NOT NULL, comment TEXT);
CREATE INDEX IF NOT EXISTS ix_ev_app ON events(app_id);
"""

class Conflict(Exception):
    """Заявку изменил кто-то другой (version не совпала)."""

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

@contextmanager
def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c; c.commit()
    except Exception:
        c.rollback(); raise
    finally:
        c.close()

def init():
    with db() as c:
        c.executescript(SCHEMA)

def row_to_app(r):
    if r is None: return None
    a = dict(r)
    for k in JSON_COLS:
        a[k] = json.loads(a[k]) if a[k] else None
    a["consent"] = bool(a["consent"])
    return a

def get_app(c, app_id):
    return row_to_app(c.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())

def insert_app(c, a):
    a["created_at"] = a["updated_at"] = now()
    c.execute("INSERT INTO applications(id,user_id,status,version,created_at,updated_at) VALUES(?,?,?,?,?,?)",
              (a["id"], a["user_id"], a["status"], 1, a["created_at"], a["updated_at"]))
    a["version"] = 1
    save_app(c, a)

def save_app(c, a):
    a["updated_at"] = now()
    vals = [json.dumps(a.get(k), ensure_ascii=False) if k in JSON_COLS else a.get(k) for k in COLS]
    cur = c.execute(f"UPDATE applications SET {','.join(k + '=?' for k in COLS)}, version=version+1 "
                    "WHERE id=? AND version=?", vals + [a["id"], a["version"]])
    if cur.rowcount == 0: raise Conflict()
    a["version"] += 1

def add_event(c, app_id, actor, frm, to, comment=None):
    c.execute("INSERT INTO events(app_id,ts,actor,from_status,to_status,comment) VALUES(?,?,?,?,?,?)",
              (app_id, now(), actor, frm, to, comment))

def events(c, app_id):
    return [dict(r) for r in c.execute("SELECT ts,actor,from_status,to_status,comment FROM events WHERE app_id=? ORDER BY id", (app_id,))]
