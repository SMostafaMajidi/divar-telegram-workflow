from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config_store import DATA_DIR, AppError

DB_PATH = DATA_DIR / "service.db"
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path = DB_PATH) -> None:
    with _lock:
        conn = connect(path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    telegram_username TEXT NOT NULL UNIQUE,
                    telegram_chat_id TEXT,
                    display_name TEXT,
                    api_key TEXT NOT NULL UNIQUE,
                    ai_enabled INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    login_username TEXT,
                    password_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS filters (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    category TEXT NOT NULL,
                    query TEXT,
                    cities_json TEXT NOT NULL,
                    exclude_json TEXT NOT NULL,
                    fields_json TEXT NOT NULL,
                    max_pages INTEGER NOT NULL DEFAULT 3,
                    destination_chat_id TEXT,
                    price_min_toman INTEGER,
                    price_max_toman INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS seen (
                    user_id TEXT NOT NULL,
                    filter_id TEXT NOT NULL,
                    token TEXT NOT NULL,
                    seen_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, filter_id, token)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS listings_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    filter_id TEXT,
                    token TEXT NOT NULL,
                    title TEXT,
                    price TEXT,
                    location TEXT,
                    url TEXT,
                    image_url TEXT,
                    filter_name TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    token TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_filters_user ON filters(user_id);
                CREATE INDEX IF NOT EXISTS idx_listings_user ON listings_cache(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(telegram_username);
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "login_username" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN login_username TEXT")
            if "password_hash" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users(login_username) "
                "WHERE login_username IS NOT NULL AND login_username != ''"
            )
            conn.commit()
        finally:
            conn.close()


def normalize_username(username: str) -> str:
    value = str(username or "").strip().lstrip("@").lower()
    if not value:
        raise AppError("Username is required.")
    return value


def normalize_login_username(username: str) -> str:
    value = normalize_username(username)
    if len(value) < 3 or len(value) > 32:
        raise AppError("یوزرنیم باید بین ۳ تا ۳۲ کاراکتر باشد.")
    if not re.fullmatch(r"[a-z0-9_]+", value):
        raise AppError("یوزرنیم فقط می‌تواند حروف انگلیسی، عدد و _ باشد.")
    return value


def hash_password(password: str) -> str:
    raw = str(password or "")
    if len(raw) < 4:
        raise AppError("رمز عبور حداقل ۴ کاراکتر باشد.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256$120000${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, rounds, salt, digest = str(password_hash or "").split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt.encode("utf-8"),
            int(rounds),
        )
        return secrets.compare_digest(check.hex(), digest)
    except Exception:
        return False


def new_api_key() -> str:
    return "dw_" + secrets.token_urlsafe(24)


def _user_public(row: dict[str, Any]) -> dict[str, Any]:
    login = (row.get("login_username") or "").strip()
    tg = row.get("telegram_username") or ""
    return {
        "id": row["id"],
        "telegram_username": tg,
        "login_username": login,
        "telegram_chat_id": row.get("telegram_chat_id") or "",
        "display_name": row.get("display_name") or login or tg,
        "api_key": row["api_key"],
        "ai_enabled": bool(row.get("ai_enabled")),
        "active": bool(row.get("active")),
        "created_at": row.get("created_at") or "",
        "linked": bool(row.get("telegram_chat_id")),
        "has_password": bool(row.get("password_hash")),
        "public_slug": login or tg,
    }


def create_user(
    telegram_username: str,
    *,
    display_name: str = "",
    ai_enabled: bool = False,
    active: bool = True,
    login_username: str = "",
    password: str = "",
) -> dict[str, Any]:
    username = normalize_username(telegram_username)
    login = normalize_login_username(login_username) if login_username else ""
    password_hash = hash_password(password) if password else None
    user_id = uuid.uuid4().hex[:12]
    api_key = new_api_key()
    with _lock:
        conn = connect()
        try:
            existing = conn.execute(
                "SELECT id FROM users WHERE telegram_username = ?", (username,)
            ).fetchone()
            if existing:
                raise AppError("This Telegram username already exists.")
            if login:
                taken = conn.execute(
                    "SELECT id FROM users WHERE lower(login_username) = ?", (login,)
                ).fetchone()
                if taken:
                    raise AppError("این یوزرنیم ورود قبلاً گرفته شده است.")
            conn.execute(
                """
                INSERT INTO users
                (id, telegram_username, telegram_chat_id, display_name, api_key, ai_enabled, active, created_at, login_username, password_hash)
                VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    display_name.strip() or login or username,
                    api_key,
                    1 if ai_enabled else 0,
                    1 if active else 0,
                    _now(),
                    login or None,
                    password_hash,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    user = get_user(user_id)
    assert user
    return user


def register_from_telegram(
    *,
    login_username: str,
    password: str,
    chat_id: str,
    telegram_username: str = "",
    display_name: str = "",
) -> dict[str, Any]:
    login = normalize_login_username(login_username)
    password_hash = hash_password(password)
    tg = normalize_username(telegram_username) if telegram_username else login
    chat_id = str(chat_id)
    with _lock:
        conn = connect()
        try:
            by_chat = conn.execute(
                "SELECT * FROM users WHERE telegram_chat_id = ?", (chat_id,)
            ).fetchone()
            login_taken = conn.execute(
                "SELECT * FROM users WHERE lower(login_username) = ?", (login,)
            ).fetchone()
            if login_taken and (not by_chat or login_taken["id"] != by_chat["id"]):
                raise AppError("این یوزرنیم قبلاً گرفته شده. یکی دیگر انتخاب کنید.")

            if by_chat:
                conn.execute(
                    """
                    UPDATE users
                    SET login_username = ?, password_hash = ?, display_name = COALESCE(NULLIF(?, ''), display_name),
                        telegram_username = CASE
                          WHEN telegram_username IS NULL OR telegram_username = '' THEN ?
                          ELSE telegram_username
                        END
                    WHERE id = ?
                    """,
                    (
                        login,
                        password_hash,
                        display_name.strip(),
                        tg,
                        by_chat["id"],
                    ),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM users WHERE id = ?", (by_chat["id"],)).fetchone()
                return _user_public(dict(row))

            tg_taken = conn.execute(
                "SELECT id FROM users WHERE telegram_username = ?", (tg,)
            ).fetchone()
            if tg_taken:
                tg = f"{login}_{uuid.uuid4().hex[:4]}"

            user_id = uuid.uuid4().hex[:12]
            conn.execute(
                """
                INSERT INTO users
                (id, telegram_username, telegram_chat_id, display_name, api_key, ai_enabled, active, created_at, login_username, password_hash)
                VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?, ?)
                """,
                (
                    user_id,
                    tg,
                    chat_id,
                    display_name.strip() or login,
                    new_api_key(),
                    _now(),
                    login,
                    password_hash,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return _user_public(dict(row))
        finally:
            conn.close()


def get_user_by_login(login_username: str) -> dict[str, Any] | None:
    login = normalize_username(login_username)
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(login_username) = ? AND active = 1",
                (login,),
            ).fetchone()
            return _user_public(dict(row)) if row else None
        finally:
            conn.close()


def get_user_by_public_slug(slug: str) -> dict[str, Any] | None:
    slug = normalize_username(slug)
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM users
                WHERE active = 1 AND (lower(login_username) = ? OR lower(telegram_username) = ?)
                """,
                (slug, slug),
            ).fetchone()
            return _user_public(dict(row)) if row else None
        finally:
            conn.close()


def authenticate_login(login_username: str, password: str) -> dict[str, Any]:
    login = normalize_username(login_username)
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(login_username) = ?",
                (login,),
            ).fetchone()
            if not row or not row["active"]:
                raise AppError("یوزرنیم یا رمز عبور نادرست است.")
            if not verify_password(password, row["password_hash"] or ""):
                raise AppError("یوزرنیم یا رمز عبور نادرست است.")
            return _user_public(dict(row))
        finally:
            conn.close()


def create_browser_session(user_id: str, days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO sessions (token, user_id, expires_at, used, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (token, user_id, expires, _now()),
            )
            conn.commit()
            return token
        finally:
            conn.close()


def list_users() -> list[dict[str, Any]]:
    with _lock:
        conn = connect()
        try:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
            return [_user_public(dict(row)) for row in rows]
        finally:
            conn.close()


def get_user(user_id: str) -> dict[str, Any] | None:
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return _user_public(dict(row)) if row else None
        finally:
            conn.close()


def get_user_by_username(username: str) -> dict[str, Any] | None:
    username = normalize_username(username)
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_username = ? OR lower(login_username) = ?",
                (username, username),
            ).fetchone()
            return _user_public(dict(row)) if row else None
        finally:
            conn.close()


def get_user_by_chat_id(chat_id: str) -> dict[str, Any] | None:
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_chat_id = ?", (str(chat_id),)
            ).fetchone()
            return _user_public(dict(row)) if row else None
        finally:
            conn.close()


def get_user_by_api_key(api_key: str) -> dict[str, Any] | None:
    key = str(api_key or "").strip()
    if not key:
        return None
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE api_key = ? AND active = 1", (key,)
            ).fetchone()
            return _user_public(dict(row)) if row else None
        finally:
            conn.close()


def update_user(user_id: str, **fields: Any) -> dict[str, Any]:
    fields = dict(fields)
    if fields.get("password"):
        fields["password_hash"] = hash_password(str(fields.pop("password")))
    if fields.get("login_username"):
        fields["login_username"] = normalize_login_username(str(fields["login_username"]))
    allowed = {
        "display_name",
        "ai_enabled",
        "active",
        "telegram_chat_id",
        "login_username",
        "password_hash",
    }
    updates: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key in {"ai_enabled", "active"}:
            value = 1 if value else 0
        updates.append(f"{key} = ?")
        values.append(value)
    if not updates:
        user = get_user(user_id)
        if not user:
            raise AppError("User not found.")
        return user
    values.append(user_id)
    with _lock:
        conn = connect()
        try:
            if fields.get("login_username"):
                taken = conn.execute(
                    "SELECT id FROM users WHERE lower(login_username) = ? AND id != ?",
                    (fields["login_username"], user_id),
                ).fetchone()
                if taken:
                    raise AppError("این یوزرنیم ورود قبلاً گرفته شده است.")
            cur = conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", values)
            if cur.rowcount == 0:
                raise AppError("User not found.")
            conn.commit()
        finally:
            conn.close()
    user = get_user(user_id)
    if not user:
        raise AppError("User not found.")
    return user


def rotate_api_key(user_id: str) -> dict[str, Any]:
    key = new_api_key()
    with _lock:
        conn = connect()
        try:
            cur = conn.execute("UPDATE users SET api_key = ? WHERE id = ?", (key, user_id))
            if cur.rowcount == 0:
                raise AppError("User not found.")
            conn.commit()
        finally:
            conn.close()
    user = get_user(user_id)
    assert user
    return user


def link_telegram_chat(username: str, chat_id: str, *, from_message: dict[str, Any] | None = None) -> dict[str, Any]:
    username = normalize_username(username)
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_username = ?", (username,)
            ).fetchone()
            if not row:
                raise AppError("این یوزرنیم در سامانه ثبت نشده. با پشتیبانی هماهنگ کنید.")
            if not row["active"]:
                raise AppError("حساب غیرفعال است.")
            display = row["display_name"]
            if from_message:
                first = str((from_message.get("from") or {}).get("first_name") or "").strip()
                if first and (not display or display == username):
                    display = first
            conn.execute(
                "UPDATE users SET telegram_chat_id = ?, display_name = ? WHERE id = ?",
                (str(chat_id), display, row["id"]),
            )
            conn.commit()
            refreshed = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            return _user_public(dict(refreshed))
        finally:
            conn.close()


def create_magic_session(user_id: str, hours: int = 12) -> str:
    token = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO sessions (token, user_id, expires_at, used, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (token, user_id, expires, _now()),
            )
            conn.commit()
        finally:
            conn.close()
    return token


def consume_magic_session(token: str) -> dict[str, Any] | None:
    """Exchange a magic login token for a browser session cookie.

    Magic links stay valid until expires_at so Telegram/link previews cannot
    permanently burn a one-time open.
    """
    token = str(token or "").strip()
    if not token:
        return None
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
            if not row or row["expires_at"] < _now():
                return None
            # Already a long-lived browser session token — reuse it.
            if not row["used"] and (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).days >= 7:
                user_row = conn.execute(
                    "SELECT * FROM users WHERE id = ?", (row["user_id"],)
                ).fetchone()
                if not user_row:
                    return None
                user = _user_public(dict(user_row))
                user["session_token"] = token
                return user

            conn.execute("UPDATE sessions SET used = 1 WHERE token = ?", (token,))
            session_token = secrets.token_urlsafe(32)
            expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            conn.execute(
                """
                INSERT INTO sessions (token, user_id, expires_at, used, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (session_token, row["user_id"], expires, _now()),
            )
            conn.commit()
            user_row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (row["user_id"],)
            ).fetchone()
            if not user_row:
                return None
            user = _user_public(dict(user_row))
            user["session_token"] = session_token
            return user
        finally:
            conn.close()


def get_session_user(token: str) -> dict[str, Any] | None:
    token = str(token or "").strip()
    if not token:
        return None
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token = ? AND used = 0", (token,)
            ).fetchone()
            if not row or row["expires_at"] < _now():
                return None
            user_row = conn.execute(
                "SELECT * FROM users WHERE id = ? AND active = 1", (row["user_id"],)
            ).fetchone()
            return _user_public(dict(user_row)) if user_row else None
        finally:
            conn.close()


def create_admin_session(hours: int = 24 * 14) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    with _lock:
        conn = connect()
        try:
            conn.execute(
                "INSERT INTO admin_sessions (token, expires_at, created_at) VALUES (?, ?, ?)",
                (token, expires, _now()),
            )
            conn.commit()
            return token
        finally:
            conn.close()


def admin_session_ok(token: str) -> bool:
    token = str(token or "").strip()
    if not token:
        return False
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT expires_at FROM admin_sessions WHERE token = ?", (token,)
            ).fetchone()
            return bool(row and row["expires_at"] >= _now())
        finally:
            conn.close()


def delete_admin_session(token: str) -> None:
    token = str(token or "").strip()
    if not token:
        return
    with _lock:
        conn = connect()
        try:
            conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
            conn.commit()
        finally:
            conn.close()


def _filter_from_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "user_id": data["user_id"],
        "name": data["name"],
        "enabled": bool(data["enabled"]),
        "category": data["category"],
        "query": data.get("query") or "",
        "cities": json.loads(data["cities_json"] or "[]"),
        "exclude_title": json.loads(data["exclude_json"] or "[]"),
        "fields": json.loads(data["fields_json"] or "{}"),
        "max_pages": int(data.get("max_pages") or 3),
        "chat_id": data.get("destination_chat_id") or "",
        "price_min_toman": data.get("price_min_toman"),
        "price_max_toman": data.get("price_max_toman"),
    }


def list_filters(user_id: str | None = None, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    with _lock:
        conn = connect()
        try:
            if user_id:
                sql = "SELECT * FROM filters WHERE user_id = ?"
                args: list[Any] = [user_id]
                if enabled_only:
                    sql += " AND enabled = 1"
                sql += " ORDER BY created_at DESC"
                rows = conn.execute(sql, args).fetchall()
            else:
                sql = "SELECT f.*, u.telegram_chat_id AS user_chat_id FROM filters f JOIN users u ON u.id = f.user_id"
                if enabled_only:
                    sql += " WHERE f.enabled = 1 AND u.active = 1"
                sql += " ORDER BY f.created_at DESC"
                rows = conn.execute(sql).fetchall()
            return [_filter_from_row(row) for row in rows]
        finally:
            conn.close()


def get_filter(filter_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    with _lock:
        conn = connect()
        try:
            if user_id:
                row = conn.execute(
                    "SELECT * FROM filters WHERE id = ? AND user_id = ?",
                    (filter_id, user_id),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM filters WHERE id = ?", (filter_id,)).fetchone()
            return _filter_from_row(row) if row else None
        finally:
            conn.close()


def upsert_filter(user_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    filter_id = str(spec.get("id") or uuid.uuid4().hex[:10])
    with _lock:
        conn = connect()
        try:
            existing = conn.execute(
                "SELECT id FROM filters WHERE id = ? AND user_id = ?",
                (filter_id, user_id),
            ).fetchone()
            values = (
                spec["name"],
                1 if spec.get("enabled", True) else 0,
                spec["category"],
                spec.get("query") or "",
                json.dumps(spec.get("cities") or [], ensure_ascii=False),
                json.dumps(spec.get("exclude_title") or [], ensure_ascii=False),
                json.dumps(spec.get("fields") or {}, ensure_ascii=False),
                int(spec.get("max_pages") or 3),
                str(spec.get("chat_id") or "").strip() or None,
                spec.get("price_min_toman"),
                spec.get("price_max_toman"),
            )
            if existing:
                conn.execute(
                    """
                    UPDATE filters SET
                        name=?, enabled=?, category=?, query=?, cities_json=?,
                        exclude_json=?, fields_json=?, max_pages=?, destination_chat_id=?,
                        price_min_toman=?, price_max_toman=?
                    WHERE id=? AND user_id=?
                    """,
                    values + (filter_id, user_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO filters
                    (id, user_id, name, enabled, category, query, cities_json, exclude_json,
                     fields_json, max_pages, destination_chat_id, price_min_toman, price_max_toman, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (filter_id, user_id) + values + (_now(),),
                )
            conn.commit()
        finally:
            conn.close()
    found = get_filter(filter_id, user_id)
    assert found
    return found


def delete_filter(filter_id: str, user_id: str) -> None:
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                "DELETE FROM filters WHERE id = ? AND user_id = ?",
                (filter_id, user_id),
            )
            if cur.rowcount == 0:
                raise AppError("Filter not found.")
            conn.commit()
        finally:
            conn.close()


def set_filter_enabled(filter_id: str, user_id: str, enabled: bool) -> dict[str, Any]:
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                "UPDATE filters SET enabled = ? WHERE id = ? AND user_id = ?",
                (1 if enabled else 0, filter_id, user_id),
            )
            if cur.rowcount == 0:
                raise AppError("Filter not found.")
            conn.commit()
        finally:
            conn.close()
    found = get_filter(filter_id, user_id)
    assert found
    return found


def is_seen(user_id: str, filter_id: str, token: str) -> bool:
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM seen WHERE user_id=? AND filter_id=? AND token=?",
                (user_id, filter_id, token),
            ).fetchone()
            return row is not None
        finally:
            conn.close()


def mark_seen(user_id: str, filter_id: str, tokens: list[str]) -> None:
    if not tokens:
        return
    with _lock:
        conn = connect()
        try:
            conn.executemany(
                "INSERT OR IGNORE INTO seen (user_id, filter_id, token, seen_at) VALUES (?, ?, ?, ?)",
                [(user_id, filter_id, token, _now()) for token in tokens],
            )
            conn.commit()
        finally:
            conn.close()


def cache_listing(user_id: str, filter_id: str, listing: dict[str, Any]) -> None:
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO listings_cache
                (user_id, filter_id, token, title, price, location, url, image_url, filter_name, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    filter_id,
                    listing.get("token") or "",
                    listing.get("title") or "",
                    listing.get("price") or "",
                    listing.get("location") or "",
                    listing.get("url") or "",
                    listing.get("image_url") or "",
                    listing.get("filter_name") or "",
                    json.dumps(listing, ensure_ascii=False),
                    _now(),
                ),
            )
            conn.execute(
                """
                DELETE FROM listings_cache WHERE id IN (
                    SELECT id FROM listings_cache WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT -1 OFFSET 500
                )
                """,
                (user_id,),
            )
            conn.commit()
        finally:
            conn.close()


def list_cached_listings(
    user_id: str, *, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    with _lock:
        conn = connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM listings_cache
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            ).fetchall()
            out = []
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except json.JSONDecodeError:
                    payload = {}
                item = {
                    "token": row["token"],
                    "title": row["title"],
                    "price": row["price"],
                    "location": row["location"],
                    "url": row["url"],
                    "image_url": row["image_url"],
                    "filter_name": row["filter_name"],
                    "filter_id": row["filter_id"],
                    "created_at": row["created_at"],
                }
                item.update({k: v for k, v in payload.items() if k not in item})
                out.append(item)
            return out
        finally:
            conn.close()


def active_users_with_filters() -> list[dict[str, Any]]:
    result = []
    for user in list_users():
        if not user["active"] or not user["linked"]:
            continue
        filters = list_filters(user["id"], enabled_only=True)
        if filters:
            result.append({"user": user, "filters": filters})
    return result
