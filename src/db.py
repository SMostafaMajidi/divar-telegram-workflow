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
_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path | None = None) -> None:
    target = path or DB_PATH
    with _lock:
        conn = connect(target)
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
                CREATE TABLE IF NOT EXISTS user_chats (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    chat_id TEXT NOT NULL,
                    chat_type TEXT,
                    name TEXT,
                    username TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, chat_id)
                );
                CREATE INDEX IF NOT EXISTS idx_filters_user ON filters(user_id);
                CREATE INDEX IF NOT EXISTS idx_listings_user ON listings_cache(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(telegram_username);
                CREATE INDEX IF NOT EXISTS idx_user_chats_user ON user_chats(user_id);
                CREATE TABLE IF NOT EXISTS invoices (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    plan_id TEXT NOT NULL,
                    amount_toman INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    ref_code TEXT NOT NULL UNIQUE,
                    payer_note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    paid_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_invoices_user ON invoices(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status, created_at DESC);
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "login_username" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN login_username TEXT")
            if "password_hash" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            if "poll_interval_minutes" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN poll_interval_minutes INTEGER")
            if "poll_offset_minutes" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN poll_offset_minutes INTEGER NOT NULL DEFAULT 0"
                )
            if "best_count" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN best_count INTEGER")
            if "plan_id" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN plan_id TEXT NOT NULL DEFAULT 'trial'")
            if "max_filters" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN max_filters INTEGER")
            if "expires_at" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN expires_at TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users(login_username) "
                "WHERE login_username IS NOT NULL AND login_username != ''"
            )
            # Ensure user_chats exists for older DBs
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_chats (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    chat_id TEXT NOT NULL,
                    chat_type TEXT,
                    name TEXT,
                    username TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, chat_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS invoices (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    plan_id TEXT NOT NULL,
                    amount_toman INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    ref_code TEXT NOT NULL UNIQUE,
                    payer_note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    paid_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_invoices_user ON invoices(user_id, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status, created_at DESC)"
            )
            inv_cols = {row[1] for row in conn.execute("PRAGMA table_info(invoices)").fetchall()}
            if inv_cols and "receipt_path" not in inv_cols:
                conn.execute("ALTER TABLE invoices ADD COLUMN receipt_path TEXT")
            if inv_cols and "receipt_name" not in inv_cols:
                conn.execute("ALTER TABLE invoices ADD COLUMN receipt_name TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    tagline TEXT,
                    price_toman INTEGER NOT NULL DEFAULT 0,
                    max_filters INTEGER NOT NULL DEFAULT 1,
                    max_criteria INTEGER,
                    poll_interval_minutes INTEGER NOT NULL DEFAULT 5,
                    ai_enabled INTEGER NOT NULL DEFAULT 0,
                    api_access INTEGER NOT NULL DEFAULT 0,
                    duration_days INTEGER NOT NULL DEFAULT 30,
                    features_json TEXT NOT NULL DEFAULT '[]',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watch_events (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    filter_id TEXT,
                    filter_name TEXT,
                    platform TEXT NOT NULL DEFAULT 'divar',
                    channel TEXT NOT NULL DEFAULT 'telegram',
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    found_count INTEGER NOT NULL DEFAULT 0,
                    new_count INTEGER NOT NULL DEFAULT 0,
                    sent_count INTEGER NOT NULL DEFAULT 0,
                    destination TEXT,
                    message TEXT,
                    detail_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_watch_events_user ON watch_events(user_id, created_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messenger_accounts (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    channel TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    username TEXT,
                    display_name TEXT,
                    linked_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, channel),
                    UNIQUE (channel, account_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS filter_destinations (
                    id TEXT PRIMARY KEY,
                    filter_id TEXT NOT NULL REFERENCES filters(id) ON DELETE CASCADE,
                    channel TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE (filter_id, channel, chat_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_filter_destinations_filter ON filter_destinations(filter_id)"
            )
            _migrate_messenger_schema(conn)
            _seed_plans(conn)
            conn.commit()
        finally:
            conn.close()


def _migrate_messenger_schema(conn: sqlite3.Connection) -> None:
    """Add channel to user_chats and backfill telegram accounts/destinations."""
    chat_cols = {row[1] for row in conn.execute("PRAGMA table_info(user_chats)").fetchall()}
    if chat_cols and "channel" not in chat_cols:
        conn.execute(
            """
            CREATE TABLE user_chats_new (
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel TEXT NOT NULL DEFAULT 'telegram',
                chat_id TEXT NOT NULL,
                chat_type TEXT,
                name TEXT,
                username TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, channel, chat_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO user_chats_new (user_id, channel, chat_id, chat_type, name, username, updated_at)
            SELECT user_id, 'telegram', chat_id, chat_type, name, username, updated_at
            FROM user_chats
            """
        )
        conn.execute("DROP TABLE user_chats")
        conn.execute("ALTER TABLE user_chats_new RENAME TO user_chats")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_chats_user ON user_chats(user_id)")

    # Backfill messenger_accounts from telegram_chat_id
    users = conn.execute(
        "SELECT id, telegram_chat_id, telegram_username, display_name FROM users WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id != ''"
    ).fetchall()
    now = _now()
    for row in users:
        conn.execute(
            """
            INSERT INTO messenger_accounts (user_id, channel, account_id, username, display_name, linked_at)
            VALUES (?, 'telegram', ?, ?, ?, ?)
            ON CONFLICT(user_id, channel) DO UPDATE SET
                account_id = excluded.account_id,
                username = COALESCE(excluded.username, messenger_accounts.username),
                display_name = COALESCE(excluded.display_name, messenger_accounts.display_name)
            """,
            (
                row["id"],
                str(row["telegram_chat_id"]),
                row["telegram_username"] or "",
                row["display_name"] or "",
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO user_chats (user_id, channel, chat_id, chat_type, name, username, updated_at)
            VALUES (?, 'telegram', ?, 'private', ?, ?, ?)
            ON CONFLICT(user_id, channel, chat_id) DO NOTHING
            """,
            (
                row["id"],
                str(row["telegram_chat_id"]),
                row["display_name"] or row["telegram_username"] or "چت شخصی",
                row["telegram_username"] or "",
                now,
            ),
        )

    # Backfill filter_destinations from destination_chat_id
    filters = conn.execute(
        "SELECT id, user_id, destination_chat_id FROM filters"
    ).fetchall()
    for filt in filters:
        existing = conn.execute(
            "SELECT 1 FROM filter_destinations WHERE filter_id = ? LIMIT 1",
            (filt["id"],),
        ).fetchone()
        if existing:
            continue
        dest = (filt["destination_chat_id"] or "").strip()
        if not dest:
            user = conn.execute(
                "SELECT telegram_chat_id FROM users WHERE id = ?", (filt["user_id"],)
            ).fetchone()
            dest = str((user["telegram_chat_id"] if user else "") or "").strip()
        if not dest:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO filter_destinations (id, filter_id, channel, chat_id, enabled, created_at)
            VALUES (?, ?, 'telegram', ?, 1, ?)
            """,
            (uuid.uuid4().hex[:12], filt["id"], dest, now),
        )


def _seed_plans(conn: sqlite3.Connection) -> None:
    from plans import DEFAULT_PLANS

    count = conn.execute("SELECT COUNT(*) AS c FROM plans").fetchone()
    if count and int(count["c"] or 0) > 0:
        return
    now = _now()
    for plan in DEFAULT_PLANS.values():
        conn.execute(
            """
            INSERT INTO plans (
                id, name, tagline, price_toman, max_filters, max_criteria,
                poll_interval_minutes, ai_enabled, api_access, duration_days,
                features_json, sort_order, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan["id"],
                plan["name"],
                plan.get("tagline") or "",
                int(plan.get("price_toman") or 0),
                int(plan.get("max_filters") or 1),
                None if plan.get("max_criteria") is None else int(plan["max_criteria"]),
                int(plan.get("poll_interval_minutes") or 5),
                1 if plan.get("ai_enabled") else 0,
                1 if plan.get("api_access") else 0,
                int(plan.get("duration_days") or 30),
                json.dumps(plan.get("features") or [], ensure_ascii=False),
                int(plan.get("sort_order") or 0),
                1 if plan.get("active", True) else 0,
                now,
            ),
        )


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


def _clamp_poll_interval(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return max(1, min(int(value), 24 * 60))


def _clamp_poll_offset(value: Any, interval: int | None = None) -> int:
    if value is None or value == "":
        return 0
    offset = max(0, int(value))
    if interval is not None and interval > 0:
        return offset % interval
    return offset


def _clamp_best_count(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return max(1, min(int(value), 10))


def _user_public(row: dict[str, Any]) -> dict[str, Any]:
    from plans import effective_max_filters, get_plan, subscription_status

    login = (row.get("login_username") or "").strip()
    tg = row.get("telegram_username") or ""
    interval = _clamp_poll_interval(row.get("poll_interval_minutes"))
    offset = _clamp_poll_offset(row.get("poll_offset_minutes"), interval)
    plan_id = str(row.get("plan_id") or "trial")
    plan = get_plan(plan_id)
    max_filters = row.get("max_filters")
    accounts = list_messenger_accounts(row["id"])
    linked = bool(accounts) or bool(row.get("telegram_chat_id"))
    user = {
        "id": row["id"],
        "telegram_username": tg,
        "login_username": login,
        "telegram_chat_id": row.get("telegram_chat_id") or "",
        "display_name": row.get("display_name") or login or tg,
        "api_key": row["api_key"],
        "ai_enabled": bool(row.get("ai_enabled")),
        "active": bool(row.get("active")),
        "created_at": row.get("created_at") or "",
        "linked": linked,
        "has_password": bool(row.get("password_hash")),
        "public_slug": login or tg,
        "poll_interval_minutes": interval,
        "poll_offset_minutes": offset,
        "best_count": _clamp_best_count(row.get("best_count")),
        "plan_id": plan_id,
        "plan_name": plan.get("name") or plan_id,
        "max_filters": int(max_filters) if max_filters is not None else None,
        "expires_at": row.get("expires_at") or "",
        "messenger_accounts": accounts,
    }
    user["effective_max_filters"] = effective_max_filters(user)
    user["subscription_status"] = subscription_status(user)
    return user


def create_user(
    telegram_username: str,
    *,
    display_name: str = "",
    ai_enabled: bool = False,
    active: bool = True,
    login_username: str = "",
    password: str = "",
    plan_id: str = "trial",
) -> dict[str, Any]:
    from plans import get_plan, plan_expiry_iso

    username = normalize_username(telegram_username)
    login = normalize_login_username(login_username) if login_username else ""
    password_hash = hash_password(password) if password else None
    user_id = uuid.uuid4().hex[:12]
    api_key = new_api_key()
    plan = get_plan(plan_id)
    expires_at = plan_expiry_iso(plan["id"])
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
                (id, telegram_username, telegram_chat_id, display_name, api_key, ai_enabled, active, created_at,
                 login_username, password_hash, plan_id, max_filters, poll_interval_minutes, expires_at)
                VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    display_name.strip() or login or username,
                    api_key,
                    1 if (ai_enabled or plan.get("ai_enabled")) else 0,
                    1 if active else 0,
                    _now(),
                    login or None,
                    password_hash,
                    plan["id"],
                    int(plan["max_filters"]),
                    int(plan["poll_interval_minutes"]),
                    expires_at,
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
                conn.execute(
                    """
                    INSERT INTO messenger_accounts (user_id, channel, account_id, username, display_name, linked_at)
                    VALUES (?, 'telegram', ?, ?, ?, ?)
                    ON CONFLICT(user_id, channel) DO UPDATE SET
                        account_id = excluded.account_id,
                        username = COALESCE(NULLIF(excluded.username, ''), messenger_accounts.username),
                        display_name = COALESCE(NULLIF(excluded.display_name, ''), messenger_accounts.display_name)
                    """,
                    (by_chat["id"], chat_id, tg, display_name.strip() or login, _now()),
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
            from plans import get_plan, plan_expiry_iso

            plan = get_plan("trial")
            conn.execute(
                """
                INSERT INTO users
                (id, telegram_username, telegram_chat_id, display_name, api_key, ai_enabled, active, created_at,
                 login_username, password_hash, plan_id, max_filters, poll_interval_minutes, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    tg,
                    chat_id,
                    display_name.strip() or login,
                    new_api_key(),
                    1 if plan.get("ai_enabled") else 0,
                    _now(),
                    login,
                    password_hash,
                    plan["id"],
                    int(plan["max_filters"]),
                    int(plan["poll_interval_minutes"]),
                    plan_expiry_iso(plan["id"]),
                ),
            )
            conn.execute(
                """
                INSERT INTO messenger_accounts (user_id, channel, account_id, username, display_name, linked_at)
                VALUES (?, 'telegram', ?, ?, ?, ?)
                """,
                (user_id, chat_id, tg, display_name.strip() or login, _now()),
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
    if "poll_interval_minutes" in fields:
        fields["poll_interval_minutes"] = _clamp_poll_interval(fields["poll_interval_minutes"])
    if "best_count" in fields:
        fields["best_count"] = _clamp_best_count(fields["best_count"])
    if "max_filters" in fields:
        raw = fields["max_filters"]
        fields["max_filters"] = None if raw in (None, "") else max(0, min(int(raw), 100))
    if "plan_id" in fields:
        from plans import get_plan

        fields["plan_id"] = get_plan(fields.get("plan_id"))["id"]
    if "expires_at" in fields:
        raw = str(fields.get("expires_at") or "").strip()
        fields["expires_at"] = raw or None
    if "poll_offset_minutes" in fields or "poll_interval_minutes" in fields:
        from config_store import poll_interval_minutes as default_poll_interval_minutes

        current = get_user(user_id)
        interval = fields.get("poll_interval_minutes") if "poll_interval_minutes" in fields else None
        if interval is None and current:
            interval = current.get("poll_interval_minutes")
        if interval is None:
            interval = default_poll_interval_minutes()
        if "poll_offset_minutes" in fields:
            fields["poll_offset_minutes"] = _clamp_poll_offset(
                fields["poll_offset_minutes"], interval
            )
        elif current is not None:
            fields["poll_offset_minutes"] = _clamp_poll_offset(
                current.get("poll_offset_minutes"), interval
            )
    allowed = {
        "display_name",
        "ai_enabled",
        "active",
        "telegram_chat_id",
        "login_username",
        "password_hash",
        "poll_interval_minutes",
        "poll_offset_minutes",
        "best_count",
        "plan_id",
        "max_filters",
        "expires_at",
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


def delete_user(user_id: str) -> None:
    with _lock:
        conn = connect()
        try:
            cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            if cur.rowcount == 0:
                raise AppError("User not found.")
            # seen has no FK cascade
            conn.execute("DELETE FROM seen WHERE user_id = ?", (user_id,))
            conn.commit()
        finally:
            conn.close()


def user_filter_count(user_id: str) -> int:
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM filters WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return int(row["c"] if row else 0)
        finally:
            conn.close()


def _chat_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("chat_id") or row.get("id") or ""),
        "channel": str(row.get("channel") or "telegram"),
        "type": str(row.get("chat_type") or row.get("type") or ""),
        "name": str(row.get("name") or "").strip(),
        "username": str(row.get("username") or "").strip(),
    }


def upsert_user_chat(
    user_id: str,
    *,
    chat_id: str,
    chat_type: str = "",
    name: str = "",
    username: str = "",
    channel: str = "telegram",
) -> dict[str, Any]:
    cid = str(chat_id or "").strip()
    ch = str(channel or "telegram").strip().lower() or "telegram"
    if not cid:
        raise AppError("chat_id is required.")
    with _lock:
        conn = connect()
        try:
            existing = conn.execute(
                "SELECT * FROM user_chats WHERE user_id = ? AND channel = ? AND chat_id = ?",
                (user_id, ch, cid),
            ).fetchone()
            merged_name = name.strip() or ((existing["name"] if existing else "") or "")
            merged_type = chat_type.strip() or ((existing["chat_type"] if existing else "") or "")
            merged_username = username.strip() or ((existing["username"] if existing else "") or "")
            conn.execute(
                """
                INSERT INTO user_chats (user_id, channel, chat_id, chat_type, name, username, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, channel, chat_id) DO UPDATE SET
                    chat_type = excluded.chat_type,
                    name = excluded.name,
                    username = excluded.username,
                    updated_at = excluded.updated_at
                """,
                (user_id, ch, cid, merged_type, merged_name, merged_username, _now()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM user_chats WHERE user_id = ? AND channel = ? AND chat_id = ?",
                (user_id, ch, cid),
            ).fetchone()
            return _chat_public(dict(row))
        finally:
            conn.close()


def list_user_chats(user_id: str, channel: str | None = None) -> list[dict[str, Any]]:
    user = get_user(user_id)
    ch_filter = str(channel or "").strip().lower() or None
    with _lock:
        conn = connect()
        try:
            if ch_filter:
                rows = conn.execute(
                    "SELECT * FROM user_chats WHERE user_id = ? AND channel = ? ORDER BY updated_at DESC",
                    (user_id, ch_filter),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM user_chats WHERE user_id = ? ORDER BY updated_at DESC",
                    (user_id,),
                ).fetchall()
            chats = {
                ( _chat_public(dict(row))["channel"], _chat_public(dict(row))["id"] ): _chat_public(dict(row))
                for row in rows
            }
        finally:
            conn.close()
    if user and user.get("telegram_chat_id") and (not ch_filter or ch_filter == "telegram"):
        private_id = str(user["telegram_chat_id"])
        key = ("telegram", private_id)
        if key not in chats:
            chats[key] = {
                "id": private_id,
                "channel": "telegram",
                "type": "private",
                "name": user.get("display_name") or user.get("login_username") or "چت شخصی",
                "username": user.get("telegram_username") or "",
            }
        elif not chats[key].get("name"):
            chats[key]["name"] = (
                user.get("display_name") or user.get("login_username") or "چت شخصی"
            )
            if not chats[key].get("type"):
                chats[key]["type"] = "private"
    # Include private chats from linked messenger accounts (bale, …).
    for acc in (user or {}).get("messenger_accounts") or []:
        ch = str(acc.get("channel") or "").strip().lower() or "telegram"
        aid = str(acc.get("account_id") or "").strip()
        if not aid:
            continue
        if ch_filter and ch != ch_filter:
            continue
        key = (ch, aid)
        if key in chats:
            continue
        chats[key] = {
            "id": aid,
            "channel": ch,
            "type": "private",
            "name": acc.get("display_name")
            or acc.get("username")
            or user.get("display_name")
            or "چت شخصی",
            "username": acc.get("username") or "",
        }
    return sorted(
        chats.values(),
        key=lambda item: (
            0 if item.get("type") == "private" else 1,
            item.get("channel") or "",
            (item.get("name") or item["id"]).lower(),
        ),
    )


def set_filter_chat(user_id: str, filter_id: str, chat_id: str | None) -> dict[str, Any]:
    """Legacy single-destination setter (telegram). Prefer set_filter_destinations."""
    value = str(chat_id or "").strip() or None
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(
                "UPDATE filters SET destination_chat_id = ? WHERE id = ? AND user_id = ?",
                (value, filter_id, user_id),
            )
            if cur.rowcount == 0:
                raise AppError("Filter not found.")
            conn.commit()
        finally:
            conn.close()
    destinations = []
    if value:
        destinations = [{"channel": "telegram", "chat_id": value, "enabled": True}]
    else:
        user = get_user(user_id)
        if user and user.get("telegram_chat_id"):
            destinations = [
                {"channel": "telegram", "chat_id": str(user["telegram_chat_id"]), "enabled": True}
            ]
    set_filter_destinations(user_id, filter_id, destinations)
    found = get_filter(filter_id, user_id)
    assert found
    return found


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
    filter_id = data["id"]
    destinations = list_filter_destinations(filter_id)
    chat_id = data.get("destination_chat_id") or ""
    if not chat_id and destinations:
        # Prefer telegram destination for legacy chat_id field.
        tg = next((d for d in destinations if d.get("channel") == "telegram"), destinations[0])
        chat_id = tg.get("chat_id") or ""
    return {
        "id": filter_id,
        "user_id": data["user_id"],
        "name": data["name"],
        "enabled": bool(data["enabled"]),
        "category": data["category"],
        "query": data.get("query") or "",
        "cities": json.loads(data["cities_json"] or "[]"),
        "exclude_title": json.loads(data["exclude_json"] or "[]"),
        "fields": json.loads(data["fields_json"] or "{}"),
        "max_pages": int(data.get("max_pages") or 3),
        "chat_id": chat_id,
        "destinations": destinations,
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


def apply_subscription(
    user_id: str,
    plan_id: str,
    *,
    renew: bool = True,
    expires_at: str | None = None,
    apply_limits: bool = True,
) -> dict[str, Any]:
    from plans import get_plan, parse_expires_at, plan_expiry_iso

    plan = get_plan(plan_id)
    fields: dict[str, Any] = {"plan_id": plan["id"], "active": True}
    if apply_limits:
        fields["max_filters"] = int(plan["max_filters"])
        fields["poll_interval_minutes"] = int(plan["poll_interval_minutes"])
        fields["ai_enabled"] = bool(plan.get("ai_enabled"))
    if expires_at is not None:
        fields["expires_at"] = str(expires_at).strip() or None
    elif renew:
        current = get_user(user_id)
        now = datetime.now(timezone.utc)
        current_exp = parse_expires_at((current or {}).get("expires_at"))
        base = current_exp if current_exp and current_exp > now else now
        fields["expires_at"] = plan_expiry_iso(plan["id"], from_when=base)
    return update_user(user_id, **fields)


def upsert_filter(user_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    from plans import assert_filter_criteria_allowed, effective_max_filters, subscription_ok

    filter_id = str(spec.get("id") or uuid.uuid4().hex[:10])
    user = get_user(user_id)
    if not user:
        raise AppError("User not found.")
    if not subscription_ok(user):
        raise AppError("اشتراک منقضی یا غیرفعال است. با پشتیبانی هماهنگ کنید.")
    assert_filter_criteria_allowed(user, spec)
    limit = effective_max_filters(user)
    with _lock:
        conn = connect()
        try:
            existing = conn.execute(
                "SELECT id FROM filters WHERE id = ? AND user_id = ?",
                (filter_id, user_id),
            ).fetchone()
            if existing is None:
                count = conn.execute(
                    "SELECT COUNT(*) AS c FROM filters WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                used = int(count["c"] if count else 0)
                if used >= limit:
                    raise AppError(f"سقف پلن شما {limit} فیلتر است. برای افزایش پلن با پشتیبانی هماهنگ کنید.")
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
    # Sync multi-destination table.
    destinations = spec.get("destinations")
    if isinstance(destinations, list):
        set_filter_destinations(user_id, filter_id, destinations)
    elif str(spec.get("chat_id") or "").strip():
        set_filter_destinations(
            user_id,
            filter_id,
            [{"channel": "telegram", "chat_id": str(spec["chat_id"]).strip(), "enabled": True}],
        )
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
    from plans import subscription_ok

    result = []
    for user in list_users():
        if not user["active"] or not user["linked"]:
            continue
        if not subscription_ok(user):
            continue
        filters = list_filters(user["id"], enabled_only=True)
        if filters:
            result.append({"user": user, "filters": filters})
    return result


def _invoice_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    from plans import format_toman, get_plan

    plan = get_plan(row["plan_id"])
    amount = int(row["amount_toman"] or 0)
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "plan_id": row["plan_id"],
        "plan_name": plan.get("name") or row["plan_id"],
        "amount_toman": amount,
        "amount_label": format_toman(amount),
        "status": row["status"],
        "ref_code": row["ref_code"],
        "payer_note": row["payer_note"] or "",
        "receipt_path": row["receipt_path"] if "receipt_path" in row.keys() else "",
        "receipt_name": row["receipt_name"] if "receipt_name" in row.keys() else "",
        "has_receipt": bool(row["receipt_path"] if "receipt_path" in row.keys() else None),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "paid_at": row["paid_at"] or "",
    }


def _new_ref_code() -> str:
    return secrets.token_hex(3).upper()


def create_invoice(user_id: str, plan_id: str) -> dict[str, Any]:
    from plans import get_plan, paid_plan_ids

    plan = get_plan(plan_id)
    if plan["id"] not in paid_plan_ids():
        raise AppError("برای این پلن فاکتور صادر نمی‌شود.")
    amount = int(plan.get("price_toman") or 0)
    if amount <= 0:
        raise AppError("مبلغ پلن نامعتبر است.")
    user = get_user(user_id)
    if not user:
        raise AppError("User not found.")

    with _lock:
        conn = connect()
        try:
            existing = conn.execute(
                """
                SELECT * FROM invoices
                WHERE user_id = ? AND plan_id = ? AND status IN ('pending', 'awaiting_review')
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, plan["id"]),
            ).fetchone()
            if existing:
                return _invoice_from_row(existing)  # type: ignore[return-value]

            invoice_id = uuid.uuid4().hex[:12]
            now = _now()
            ref = _new_ref_code()
            for _ in range(5):
                clash = conn.execute("SELECT 1 FROM invoices WHERE ref_code = ?", (ref,)).fetchone()
                if not clash:
                    break
                ref = _new_ref_code()
            conn.execute(
                """
                INSERT INTO invoices
                (id, user_id, plan_id, amount_toman, status, ref_code, payer_note, created_at, updated_at, paid_at)
                VALUES (?, ?, ?, ?, 'pending', ?, '', ?, ?, NULL)
                """,
                (invoice_id, user_id, plan["id"], amount, ref, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            return _invoice_from_row(row)  # type: ignore[return-value]
        finally:
            conn.close()


def get_invoice(invoice_id: str) -> dict[str, Any] | None:
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            return _invoice_from_row(row)
        finally:
            conn.close()


def list_user_invoices(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with _lock:
        conn = connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM invoices WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, max(1, min(int(limit), 100))),
            ).fetchall()
            return [_invoice_from_row(row) for row in rows]  # type: ignore[misc]
        finally:
            conn.close()


def list_invoices(*, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        conn = connect()
        try:
            if status:
                rows = conn.execute(
                    """
                    SELECT i.*, u.display_name, u.login_username, u.telegram_username
                    FROM invoices i
                    LEFT JOIN users u ON u.id = i.user_id
                    WHERE i.status = ?
                    ORDER BY i.created_at DESC LIMIT ?
                    """,
                    (status, max(1, min(int(limit), 200))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT i.*, u.display_name, u.login_username, u.telegram_username
                    FROM invoices i
                    LEFT JOIN users u ON u.id = i.user_id
                    ORDER BY i.created_at DESC LIMIT ?
                    """,
                    (max(1, min(int(limit), 200)),),
                ).fetchall()
            out = []
            for row in rows:
                inv = _invoice_from_row(row)
                if not inv:
                    continue
                inv["user_name"] = row["display_name"] or ""
                inv["login_username"] = row["login_username"] or ""
                inv["telegram_username"] = row["telegram_username"] or ""
                out.append(inv)
            return out
        finally:
            conn.close()


def mark_invoice_paid_by_user(
    invoice_id: str,
    user_id: str,
    payer_note: str = "",
    *,
    receipt_path: str | None = None,
    receipt_name: str | None = None,
) -> dict[str, Any]:
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not row or row["user_id"] != user_id:
                raise AppError("فاکتور پیدا نشد.")
            if row["status"] not in {"pending", "awaiting_review"}:
                raise AppError("این فاکتور قابل به‌روزرسانی نیست.")
            existing_receipt = ""
            if "receipt_path" in row.keys():
                existing_receipt = row["receipt_path"] or ""
            new_receipt = receipt_path if receipt_path is not None else existing_receipt
            if not new_receipt:
                raise AppError("فیش واریز را آپلود کنید.")
            now = _now()
            conn.execute(
                """
                UPDATE invoices
                SET status = 'awaiting_review',
                    payer_note = ?,
                    receipt_path = ?,
                    receipt_name = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(payer_note or "").strip()[:200],
                    new_receipt,
                    (receipt_name if receipt_name is not None else (row["receipt_name"] if "receipt_name" in row.keys() else ""))
                    or "",
                    now,
                    invoice_id,
                ),
            )
            conn.commit()
            refreshed = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            return _invoice_from_row(refreshed)  # type: ignore[return-value]
        finally:
            conn.close()


def save_invoice_receipt(
    invoice_id: str,
    user_id: str,
    *,
    filename: str,
    content: bytes,
    content_type: str,
    payer_note: str = "",
) -> dict[str, Any]:
    invoice = get_invoice(invoice_id)
    if not invoice or invoice["user_id"] != user_id:
        raise AppError("فاکتور پیدا نشد.")
    if invoice["status"] not in {"pending", "awaiting_review"}:
        raise AppError("این فاکتور قابل به‌روزرسانی نیست.")
    mime = (content_type or "").split(";")[0].strip().lower()
    allowed = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }
    if mime not in allowed:
        # sniff from filename
        lower = filename.lower()
        if lower.endswith(".pdf"):
            mime = "application/pdf"
        elif lower.endswith(".png"):
            mime = "image/png"
        elif lower.endswith(".webp"):
            mime = "image/webp"
        elif lower.endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        else:
            raise AppError("فقط عکس (JPG/PNG/WEBP) یا PDF مجاز است.")
    if len(content) < 32:
        raise AppError("فایل فیش خالی یا ناقص است.")
    if len(content) > 6 * 1024 * 1024:
        raise AppError("حجم فیش حداکثر ۶ مگابایت باشد.")
    receipts_dir = DATA_DIR / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    ext = allowed[mime]
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(filename or f"receipt{ext}").name)[:80]
    stored = f"{invoice_id}{ext}"
    path = receipts_dir / stored
    # remove old receipt files for this invoice
    for old in receipts_dir.glob(f"{invoice_id}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    path.write_bytes(content)
    return mark_invoice_paid_by_user(
        invoice_id,
        user_id,
        payer_note,
        receipt_path=stored,
        receipt_name=safe_name or stored,
    )


def invoice_receipt_file(invoice_id: str) -> tuple[Path, str, str] | None:
    invoice = get_invoice(invoice_id)
    if not invoice or not invoice.get("receipt_path"):
        return None
    path = (DATA_DIR / "receipts" / Path(invoice["receipt_path"]).name).resolve()
    receipts_root = (DATA_DIR / "receipts").resolve()
    if receipts_root not in path.parents and path.parent != receipts_root:
        return None
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(suffix, "application/octet-stream")
    return path, mime, invoice.get("receipt_name") or path.name


def confirm_invoice(invoice_id: str) -> dict[str, Any]:
    invoice = get_invoice(invoice_id)
    if not invoice:
        raise AppError("فاکتور پیدا نشد.")
    if invoice["status"] == "paid":
        user = get_user(invoice["user_id"])
        return {"invoice": invoice, "user": user}
    if invoice["status"] not in {"pending", "awaiting_review"}:
        raise AppError("این فاکتور قابل تأیید نیست.")
    if not invoice.get("has_receipt"):
        raise AppError("بدون فیش واریز نمی‌توان تأیید کرد.")
    # Activate account + apply plan limits + set expiry from plan duration.
    user = apply_subscription(
        invoice["user_id"],
        invoice["plan_id"],
        renew=True,
        apply_limits=True,
    )
    with _lock:
        conn = connect()
        try:
            now = _now()
            conn.execute(
                """
                UPDATE invoices
                SET status = 'paid', paid_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, invoice_id),
            )
            # Close other open invoices for the same user+plan.
            conn.execute(
                """
                UPDATE invoices
                SET status = 'cancelled', updated_at = ?
                WHERE user_id = ? AND plan_id = ? AND id != ?
                  AND status IN ('pending', 'awaiting_review')
                """,
                (now, invoice["user_id"], invoice["plan_id"], invoice_id),
            )
            conn.commit()
        finally:
            conn.close()
    out = get_invoice(invoice_id)
    assert out
    return {"invoice": out, "user": user}


def reject_invoice(invoice_id: str) -> dict[str, Any]:
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not row:
                raise AppError("فاکتور پیدا نشد.")
            if row["status"] not in {"pending", "awaiting_review"}:
                raise AppError("این فاکتور قابل رد نیست.")
            now = _now()
            conn.execute(
                """
                UPDATE invoices SET status = 'rejected', updated_at = ? WHERE id = ?
                """,
                (now, invoice_id),
            )
            conn.commit()
            refreshed = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            return _invoice_from_row(refreshed)  # type: ignore[return-value]
        finally:
            conn.close()


def _plan_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    try:
        features = json.loads(row["features_json"] or "[]")
    except json.JSONDecodeError:
        features = []
    if not isinstance(features, list):
        features = []
    max_criteria = row["max_criteria"]
    return {
        "id": row["id"],
        "name": row["name"],
        "tagline": row["tagline"] or "",
        "price_toman": int(row["price_toman"] or 0),
        "max_filters": int(row["max_filters"] or 1),
        "max_criteria": None if max_criteria is None else int(max_criteria),
        "poll_interval_minutes": int(row["poll_interval_minutes"] or 5),
        "ai_enabled": bool(row["ai_enabled"]),
        "api_access": bool(row["api_access"]),
        "duration_days": int(row["duration_days"] or 30),
        "features": [str(x) for x in features],
        "sort_order": int(row["sort_order"] or 0),
        "active": bool(row["active"]),
        "updated_at": row["updated_at"] or "",
    }


def list_plan_rows(*, include_inactive: bool = False) -> list[dict[str, Any]]:
    with _lock:
        conn = connect()
        try:
            if include_inactive:
                rows = conn.execute(
                    "SELECT * FROM plans ORDER BY sort_order ASC, name ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM plans WHERE active = 1 ORDER BY sort_order ASC, name ASC"
                ).fetchall()
            return [_plan_from_row(row) for row in rows]  # type: ignore[misc]
        finally:
            conn.close()


def get_plan_row(plan_id: str) -> dict[str, Any] | None:
    key = str(plan_id or "").strip().lower()
    if not key:
        return None
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM plans WHERE id = ?", (key,)).fetchone()
            return _plan_from_row(row)
        finally:
            conn.close()


def upsert_plan(body: dict[str, Any], *, create: bool = False) -> dict[str, Any]:
    plan_id = str(body.get("id") or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", plan_id or ""):
        raise AppError("شناسه پلن باید انگلیسی کوچک، عدد و _ باشد (۲ تا ۳۲ کاراکتر).")
    name = str(body.get("name") or "").strip()
    if not name:
        raise AppError("نام پلن الزامی است.")
    features = body.get("features")
    if isinstance(features, str):
        features = [line.strip() for line in features.splitlines() if line.strip()]
    if not isinstance(features, list):
        features = []
    features = [str(x).strip() for x in features if str(x).strip()]
    max_criteria_raw = body.get("max_criteria")
    if max_criteria_raw in (None, "", "null"):
        max_criteria = None
    else:
        parsed = int(max_criteria_raw)
        # 0 = unlimited
        max_criteria = None if parsed <= 0 else max(1, min(parsed, 50))
    now = _now()
    values = (
        name,
        str(body.get("tagline") or "").strip(),
        max(0, int(body.get("price_toman") or 0)),
        max(0, min(int(body.get("max_filters") or 1), 100)),
        max_criteria,
        max(1, min(int(body.get("poll_interval_minutes") or 5), 1440)),
        1 if body.get("ai_enabled") else 0,
        1 if body.get("api_access") else 0,
        max(1, min(int(body.get("duration_days") or 30), 3650)),
        json.dumps(features, ensure_ascii=False),
        int(body.get("sort_order") or 0),
        1 if body.get("active", True) else 0,
        now,
        plan_id,
    )
    with _lock:
        conn = connect()
        try:
            existing = conn.execute("SELECT id FROM plans WHERE id = ?", (plan_id,)).fetchone()
            if create and existing:
                raise AppError("این شناسه پلن از قبل هست.")
            if not existing and not create:
                # allow upsert from editor even if missing
                pass
            if existing:
                conn.execute(
                    """
                    UPDATE plans SET
                        name=?, tagline=?, price_toman=?, max_filters=?, max_criteria=?,
                        poll_interval_minutes=?, ai_enabled=?, api_access=?, duration_days=?,
                        features_json=?, sort_order=?, active=?, updated_at=?
                    WHERE id=?
                    """,
                    values,
                )
            else:
                conn.execute(
                    """
                    INSERT INTO plans (
                        name, tagline, price_toman, max_filters, max_criteria,
                        poll_interval_minutes, ai_enabled, api_access, duration_days,
                        features_json, sort_order, active, updated_at, id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            conn.commit()
        finally:
            conn.close()
    plan = get_plan_row(plan_id)
    assert plan
    return plan


def delete_plan(plan_id: str) -> None:
    key = str(plan_id or "").strip().lower()
    if key == "trial":
        raise AppError("پلن آزمایشی قابل حذف نیست (پایهٔ سیستم است).")
    with _lock:
        conn = connect()
        try:
            exists = conn.execute("SELECT id FROM plans WHERE id = ?", (key,)).fetchone()
            if not exists:
                raise AppError("پلن پیدا نشد.")
            used = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE plan_id = ?", (key,)
            ).fetchone()
            count = int(used["c"] if used else 0)
            if count > 0:
                # Move customers off this plan before deleting.
                conn.execute(
                    "UPDATE users SET plan_id = 'trial' WHERE plan_id = ?",
                    (key,),
                )
            cur = conn.execute("DELETE FROM plans WHERE id = ?", (key,))
            if cur.rowcount == 0:
                raise AppError("پلن پیدا نشد.")
            conn.commit()
        finally:
            conn.close()


WATCH_EVENT_KEEP = 200


def _watch_event_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    detail = {}
    raw = row["detail_json"] if "detail_json" in row.keys() else None
    if raw:
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {}
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "filter_id": row["filter_id"] or "",
        "filter_name": row["filter_name"] or "",
        "platform": row["platform"] or "divar",
        "channel": row["channel"] or "telegram",
        "action": row["action"],
        "status": row["status"],
        "found_count": int(row["found_count"] or 0),
        "new_count": int(row["new_count"] or 0),
        "sent_count": int(row["sent_count"] or 0),
        "destination": row["destination"] or "",
        "message": row["message"] or "",
        "detail": detail,
        "created_at": row["created_at"],
    }


def log_watch_event(
    user_id: str,
    *,
    action: str,
    status: str,
    filter_id: str | None = None,
    filter_name: str | None = None,
    platform: str = "divar",
    channel: str = "telegram",
    found_count: int = 0,
    new_count: int = 0,
    sent_count: int = 0,
    destination: str | None = None,
    message: str = "",
    detail: dict[str, Any] | None = None,
    keep: int = WATCH_EVENT_KEEP,
) -> dict[str, Any]:
    event_id = uuid.uuid4().hex[:12]
    now = _now()
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO watch_events (
                    id, user_id, filter_id, filter_name, platform, channel,
                    action, status, found_count, new_count, sent_count,
                    destination, message, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    user_id,
                    filter_id,
                    filter_name or "",
                    platform or "divar",
                    channel or "telegram",
                    action,
                    status,
                    int(found_count or 0),
                    int(new_count or 0),
                    int(sent_count or 0),
                    destination or "",
                    (message or "")[:500],
                    json.dumps(detail or {}, ensure_ascii=False),
                    now,
                ),
            )
            # Keep only the newest N events per user.
            conn.execute(
                """
                DELETE FROM watch_events
                WHERE user_id = ?
                  AND id NOT IN (
                    SELECT id FROM watch_events
                    WHERE user_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                  )
                """,
                (user_id, user_id, max(20, int(keep or WATCH_EVENT_KEEP))),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM watch_events WHERE id = ?", (event_id,)).fetchone()
            return _watch_event_from_row(row)  # type: ignore[return-value]
        finally:
            conn.close()


def list_watch_events(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        conn = connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM watch_events
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, max(1, min(int(limit or 50), 200))),
            ).fetchall()
            return [_watch_event_from_row(row) for row in rows]  # type: ignore[misc]
        finally:
            conn.close()


def list_messenger_accounts(user_id: str) -> list[dict[str, Any]]:
    with _lock:
        conn = connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM messenger_accounts
                WHERE user_id = ?
                ORDER BY linked_at DESC
                """,
                (user_id,),
            ).fetchall()
            return [
                {
                    "channel": row["channel"],
                    "account_id": row["account_id"],
                    "username": row["username"] or "",
                    "display_name": row["display_name"] or "",
                    "linked_at": row["linked_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()


def get_user_by_messenger_account(channel: str, account_id: str) -> dict[str, Any] | None:
    ch = str(channel or "").strip().lower()
    aid = str(account_id or "").strip()
    if not ch or not aid:
        return None
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                """
                SELECT u.* FROM messenger_accounts m
                JOIN users u ON u.id = m.user_id
                WHERE m.channel = ? AND m.account_id = ?
                """,
                (ch, aid),
            ).fetchone()
            if row:
                return _user_public(dict(row))
            if ch == "telegram":
                row = conn.execute(
                    "SELECT * FROM users WHERE telegram_chat_id = ?", (aid,)
                ).fetchone()
                return _user_public(dict(row)) if row else None
            return None
        finally:
            conn.close()


def link_messenger_account(
    user_id: str,
    *,
    channel: str,
    account_id: str,
    username: str = "",
    display_name: str = "",
) -> dict[str, Any]:
    ch = str(channel or "").strip().lower()
    aid = str(account_id or "").strip()
    if not ch or not aid:
        raise AppError("channel و account_id لازم است.")
    with _lock:
        conn = connect()
        try:
            clash = conn.execute(
                """
                SELECT user_id FROM messenger_accounts
                WHERE channel = ? AND account_id = ? AND user_id != ?
                """,
                (ch, aid, user_id),
            ).fetchone()
            if clash:
                raise AppError("این حساب پیام‌رسان به کاربر دیگری وصل است.")
            conn.execute(
                """
                INSERT INTO messenger_accounts (user_id, channel, account_id, username, display_name, linked_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, channel) DO UPDATE SET
                    account_id = excluded.account_id,
                    username = COALESCE(NULLIF(excluded.username, ''), messenger_accounts.username),
                    display_name = COALESCE(NULLIF(excluded.display_name, ''), messenger_accounts.display_name),
                    linked_at = excluded.linked_at
                """,
                (user_id, ch, aid, username.strip(), display_name.strip(), _now()),
            )
            if ch == "telegram":
                conn.execute(
                    "UPDATE users SET telegram_chat_id = ? WHERE id = ?",
                    (aid, user_id),
                )
            conn.commit()
        finally:
            conn.close()
    upsert_user_chat(
        user_id,
        channel=ch,
        chat_id=aid,
        chat_type="private",
        name=display_name or username or "چت شخصی",
        username=username,
    )
    user = get_user(user_id)
    assert user
    return user


def link_messenger_by_login(
    *,
    channel: str,
    account_id: str,
    login_username: str,
    password: str,
    username: str = "",
    display_name: str = "",
) -> dict[str, Any]:
    user = authenticate_login(login_username, password)
    return link_messenger_account(
        user["id"],
        channel=channel,
        account_id=account_id,
        username=username,
        display_name=display_name or user.get("display_name") or "",
    )


def list_filter_destinations(filter_id: str) -> list[dict[str, Any]]:
    with _lock:
        conn = connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM filter_destinations
                WHERE filter_id = ?
                ORDER BY created_at ASC
                """,
                (filter_id,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "channel": row["channel"],
                    "chat_id": row["chat_id"],
                    "enabled": bool(row["enabled"]),
                }
                for row in rows
            ]
        finally:
            conn.close()


def set_filter_destinations(
    user_id: str,
    filter_id: str,
    destinations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    filt = get_filter(filter_id, user_id)
    if not filt:
        raise AppError("Filter not found.")
    cleaned: list[tuple[str, str, bool]] = []
    seen: set[tuple[str, str]] = set()
    for item in destinations or []:
        ch = str(item.get("channel") or "telegram").strip().lower() or "telegram"
        cid = str(item.get("chat_id") or "").strip()
        if not cid:
            continue
        key = (ch, cid)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append((ch, cid, bool(item.get("enabled", True))))
    with _lock:
        conn = connect()
        try:
            conn.execute("DELETE FROM filter_destinations WHERE filter_id = ?", (filter_id,))
            legacy_chat = None
            for ch, cid, enabled in cleaned:
                conn.execute(
                    """
                    INSERT INTO filter_destinations (id, filter_id, channel, chat_id, enabled, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (uuid.uuid4().hex[:12], filter_id, ch, cid, 1 if enabled else 0, _now()),
                )
                if legacy_chat is None and ch == "telegram" and enabled:
                    legacy_chat = cid
            if legacy_chat is None and cleaned:
                legacy_chat = cleaned[0][1] if cleaned[0][2] else None
            conn.execute(
                "UPDATE filters SET destination_chat_id = ? WHERE id = ? AND user_id = ?",
                (legacy_chat, filter_id, user_id),
            )
            conn.commit()
        finally:
            conn.close()
    return list_filter_destinations(filter_id)


def resolve_filter_destinations(user: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, str]]:
    """Return enabled destinations for watch delivery."""
    destinations = list(spec.get("destinations") or [])
    if not destinations and spec.get("id"):
        destinations = list_filter_destinations(str(spec["id"]))
    out: list[dict[str, str]] = []
    for item in destinations:
        if item.get("enabled") is False:
            continue
        ch = str(item.get("channel") or "telegram").strip().lower() or "telegram"
        cid = str(item.get("chat_id") or "").strip()
        if cid:
            out.append({"channel": ch, "chat_id": cid})
    if out:
        return out
    # Legacy fallbacks
    legacy = str(spec.get("chat_id") or "").strip()
    if legacy:
        return [{"channel": "telegram", "chat_id": legacy}]
    tg = str(user.get("telegram_chat_id") or "").strip()
    if tg:
        return [{"channel": "telegram", "chat_id": tg}]
    for acc in user.get("messenger_accounts") or []:
        aid = str(acc.get("account_id") or "").strip()
        if aid:
            return [{"channel": str(acc.get("channel") or "telegram"), "chat_id": aid}]
    return []
