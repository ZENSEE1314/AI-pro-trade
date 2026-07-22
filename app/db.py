"""SQLite storage for users, settings, positions, and order history.

API keys are encrypted at rest with Fernet using SECRET_KEY.
DB lives in DATA_DIR (mount a Railway volume there in production).
"""

import base64
import hashlib
import os
import sqlite3
import time
from pathlib import Path

from cryptography.fernet import Fernet

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "app.db"
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()))


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            pw_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            api_key_enc TEXT DEFAULT '',
            api_secret_enc TEXT DEFAULT '',
            size_usdt REAL DEFAULT 50,
            live INTEGER DEFAULT 0,
            active INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS positions (
            user_id INTEGER REFERENCES users(id),
            symbol TEXT NOT NULL,
            side INTEGER NOT NULL DEFAULT 0,
            qty REAL NOT NULL DEFAULT 0,
            entry_price REAL DEFAULT 0,
            PRIMARY KEY (user_id, symbol)
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            ts INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            info TEXT DEFAULT ''
        );
        """)
        # migration: wallet-percent sizing (default 10% of wallet per token)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(settings)")}
        if "size_mode" not in cols:
            conn.execute("ALTER TABLE settings ADD COLUMN size_mode TEXT DEFAULT 'percent'")
            conn.execute("ALTER TABLE settings ADD COLUMN size_pct REAL DEFAULT 10")


def create_user(email: str, pw_hash: str, salt: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, pw_hash, salt, created_at) VALUES (?,?,?,?)",
            (email.lower().strip(), pw_hash, salt, int(time.time())))
        conn.execute("INSERT INTO settings (user_id) VALUES (?)", (cur.lastrowid,))
        return cur.lastrowid


def get_user_by_email(email: str):
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()


def get_settings(user_id: int):
    with connect() as conn:
        return conn.execute("SELECT * FROM settings WHERE user_id=?", (user_id,)).fetchone()


def update_settings(user_id: int, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE settings SET {cols} WHERE user_id=?", (*fields.values(), user_id))


def active_traders() -> list:
    with connect() as conn:
        return conn.execute("SELECT * FROM settings WHERE active=1").fetchall()


def get_position(user_id: int, symbol: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM positions WHERE user_id=? AND symbol=?",
                           (user_id, symbol)).fetchone()
        return row


def set_position(user_id: int, symbol: str, side: int, qty: float, entry_price: float):
    with connect() as conn:
        conn.execute("""INSERT INTO positions (user_id, symbol, side, qty, entry_price)
                        VALUES (?,?,?,?,?)
                        ON CONFLICT(user_id, symbol)
                        DO UPDATE SET side=?, qty=?, entry_price=?""",
                     (user_id, symbol, side, qty, entry_price, side, qty, entry_price))


def log_order(user_id: int, symbol: str, side: str, qty: float, price: float,
              mode: str, status: str, info: str = ""):
    with connect() as conn:
        conn.execute("""INSERT INTO orders (user_id, ts, symbol, side, qty, price, mode, status, info)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                     (user_id, int(time.time()), symbol, side, qty, price, mode, status, info[:300]))


def recent_orders(user_id: int, limit: int = 50) -> list:
    with connect() as conn:
        return conn.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?",
                            (user_id, limit)).fetchall()
