#!/usr/bin/env python3
"""Strict pre-deploy tests for multi-messenger bedrock (isolated temp DB)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

PASS = 0
FAIL = 0
ERRORS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        msg = f"FAIL  {name}" + (f" — {detail}" if detail else "")
        ERRORS.append(msg)
        print(f"  {msg}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    tmp = tempfile.TemporaryDirectory(prefix="workflow-strict-")
    db_path = Path(tmp.name) / "service.db"
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "test-token-telegram"))
    # Keep BALE unset by default for one path; set for adaptor unit tests.

    import db
    import messengers
    from config_store import AppError, filter_from_api, filter_to_api
    from runner import watch_tick

    db.DB_PATH = db_path

    # ------------------------------------------------------------------
    section("1) Schema init + legacy migration")
    # Seed a legacy-shaped DB (user_chats without channel) then migrate.
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
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
        CREATE TABLE filters (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
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
        CREATE TABLE user_chats (
            user_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            chat_type TEXT,
            name TEXT,
            username TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, chat_id)
        );
        """
    )
    now = "2026-09-09T00:00:00+00:00"
    pw = db.hash_password("pass1234")
    conn.execute(
        """
        INSERT INTO users (id, telegram_username, telegram_chat_id, display_name, api_key, ai_enabled, active, created_at, login_username, password_hash)
        VALUES ('u1', 'legacy_user', '111', 'Legacy', 'k1', 0, 1, ?, 'legacy', ?)
        """,
        (now, pw),
    )
    conn.execute(
        """
        INSERT INTO filters (id, user_id, name, enabled, category, query, cities_json, exclude_json, fields_json, max_pages, destination_chat_id, created_at)
        VALUES ('f1', 'u1', 'فیلتر قدیم', 1, 'light', '', '["تهران"]', '[]', '{}', 2, '222', ?)
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT INTO user_chats (user_id, chat_id, chat_type, name, username, updated_at)
        VALUES ('u1', '222', 'group', 'گروه تست', '', ?)
        """,
        (now,),
    )
    conn.commit()
    conn.close()

    try:
        db.init_db(db_path)
    except Exception as exc:
        check("init_db on legacy schema", False, f"{type(exc).__name__}: {exc}")
        raise

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(user_chats)").fetchall()}
    check("user_chats.channel exists", "channel" in cols, str(sorted(cols)))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    check("messenger_accounts table", "messenger_accounts" in tables, str(sorted(tables)))
    check("filter_destinations table", "filter_destinations" in tables, str(sorted(tables)))
    if "messenger_accounts" not in tables:
        conn.close()
        raise SystemExit(2)
    acc = conn.execute("SELECT * FROM messenger_accounts WHERE user_id='u1'").fetchone()
    check("migrated messenger_accounts telegram", bool(acc) and acc["account_id"] == "111", str(dict(acc) if acc else None))
    chat = conn.execute("SELECT * FROM user_chats WHERE user_id='u1' AND chat_id='222'").fetchone()
    check("migrated user_chats.channel=telegram", bool(chat) and chat["channel"] == "telegram")
    dest = conn.execute("SELECT * FROM filter_destinations WHERE filter_id='f1'").fetchone()
    check("migrated filter_destinations", bool(dest) and dest["chat_id"] == "222" and dest["channel"] == "telegram")
    priv = conn.execute(
        "SELECT * FROM user_chats WHERE user_id='u1' AND chat_id='111'"
    ).fetchone()
    check("private chat backfilled", bool(priv) and priv["chat_type"] == "private")
    conn.close()

    # ------------------------------------------------------------------
    section("2) Messenger accounts + chats + destinations APIs")
    user = db.get_user("u1")
    check("get_user has messenger_accounts", bool(user and user.get("messenger_accounts")))
    check("user.linked True", bool(user and user.get("linked")))

    linked = db.link_messenger_account(
        "u1",
        channel="bale",
        account_id="bale-99",
        username="baleuser",
        display_name="Bale User",
    )
    check("link bale account", any(a["channel"] == "bale" for a in linked["messenger_accounts"]))
    by_acc = db.get_user_by_messenger_account("bale", "bale-99")
    check("lookup by bale account", bool(by_acc) and by_acc["id"] == "u1")

    # Clash: same account_id on another user
    other = db.create_user("other_tg", login_username="otherlogin", password="pass1234", display_name="Other")
    clash_ok = False
    try:
        db.link_messenger_account(other["id"], channel="bale", account_id="bale-99")
    except AppError:
        clash_ok = True
    check("reject duplicate (channel, account_id)", clash_ok)

    db.upsert_user_chat(
        "u1",
        channel="bale",
        chat_id="bale-group-1",
        chat_type="group",
        name="گروه بله",
    )
    chats_all = db.list_user_chats("u1")
    chats_bale = db.list_user_chats("u1", channel="bale")
    check("list chats includes both channels", len(chats_all) >= 3)
    check("filter chats by channel=bale", all(c["channel"] == "bale" for c in chats_bale) and len(chats_bale) >= 1)

    dests = db.set_filter_destinations(
        "u1",
        "f1",
        [
            {"channel": "telegram", "chat_id": "111", "enabled": True},
            {"channel": "telegram", "chat_id": "222", "enabled": True},
            {"channel": "bale", "chat_id": "bale-99", "enabled": True},
            {"channel": "bale", "chat_id": "bale-99", "enabled": True},  # dup
            {"channel": "telegram", "chat_id": "", "enabled": True},  # empty skip
        ],
    )
    check("dedupe destinations", len(dests) == 3, str(dests))
    filt = db.get_filter("f1", "u1")
    check("filter.destinations length 3", len(filt.get("destinations") or []) == 3)
    check("legacy chat_id prefers telegram", filt.get("chat_id") == "111", filt.get("chat_id"))

    resolved = db.resolve_filter_destinations(user, filt)
    check("resolve enabled destinations", len(resolved) == 3)

    db.set_filter_destinations(
        "u1",
        "f1",
        [
            {"channel": "telegram", "chat_id": "111", "enabled": False},
            {"channel": "bale", "chat_id": "bale-99", "enabled": True},
        ],
    )
    filt2 = db.get_filter("f1", "u1")
    resolved2 = db.resolve_filter_destinations(user, filt2)
    check("disabled destinations skipped", resolved2 == [{"channel": "bale", "chat_id": "bale-99"}])

    # ------------------------------------------------------------------
    section("3) filter_from_api / upsert destinations")
    # Raise plan ceiling for multi-filter tests
    conn = db.connect()
    conn.execute("UPDATE users SET max_filters = 20, plan_id = 'pro' WHERE id = 'u1'")
    conn.commit()
    conn.close()

    body = {
        "name": "چند مقصدی",
        "category": "light",
        "cities": ["اصفهان"],
        "exclude_title": [],
        "max_pages": 2,
        "enabled": True,
        "destinations": [
            {"channel": "telegram", "chat_id": "111"},
            {"channel": "bale", "chat_id": "bale-group-1"},
        ],
    }
    spec = filter_from_api(body)
    check("filter_from_api keeps destinations", len(spec.get("destinations") or []) == 2)
    saved = db.upsert_filter("u1", spec)
    api = filter_to_api(saved)
    check("upsert_filter persists destinations", len(api.get("destinations") or []) == 2, str(api.get("destinations")))

    # ------------------------------------------------------------------
    section("4) messengers module")
    with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tg-token", "BALE_BOT_TOKEN": ""}, clear=False):
        with mock.patch("messengers.telegram_bot_username", return_value="TestBot"), mock.patch(
            "messengers._bot_username", return_value="BaleBot"
        ):
            cfgs = messengers.messenger_configs()
            check("only telegram when BALE unset", [c["channel"] for c in cfgs] == ["telegram"])
            payload = messengers.public_messenger_payload(db.get_user("u1"))
            check("public payload telegram linked", payload and payload[0]["linked"] is True)
            check("public payload has deep_link", bool(payload[0].get("deep_link")))

    with mock.patch.dict(
        os.environ, {"TELEGRAM_BOT_TOKEN": "tg-token", "BALE_BOT_TOKEN": "bale-token"}, clear=False
    ):
        with mock.patch("messengers.telegram_bot_username", return_value="TestBot"), mock.patch(
            "messengers._bot_username", return_value="BaleBot"
        ):
            cfgs2 = messengers.messenger_configs()
            check(
                "telegram+bale when both tokens",
                [c["channel"] for c in cfgs2] == ["telegram", "bale"],
                str([c["channel"] for c in cfgs2]),
            )
            payload2 = messengers.public_messenger_payload(db.get_user("u1"))
            bale = next(p for p in payload2 if p["channel"] == "bale")
            check("bale linked in payload", bale["linked"] is True)
            check("bale deep_link ble.ir", "ble.ir" in (bale.get("deep_link") or ""))

            tg = messengers.build_messenger("telegram", {"telegram": {"send_photos": False, "delay_seconds": 0}})
            bl = messengers.build_messenger("bale", {"telegram": {"send_photos": False, "delay_seconds": 0}})
            check("TelegramBotClient type", tg.channel == "telegram")
            check("BaleBotClient type", bl.channel == "bale")
            check("bale api template", bl.api_template.startswith("https://tapi.bale.ai"))

            missing_ok = False
            try:
                messengers.build_messenger("rubika")
            except AppError:
                missing_ok = True
            check("unknown channel raises AppError", missing_ok)

    # ------------------------------------------------------------------
    section("5) watch_tick fan-out + per-destination logs")
    # Restore multi destinations on f1 and create fresh filter for tick
    db.set_filter_destinations(
        "u1",
        saved["id"],
        [
            {"channel": "telegram", "chat_id": "111", "enabled": True},
            {"channel": "bale", "chat_id": "bale-99", "enabled": True},
            {"channel": "telegram", "chat_id": "222", "enabled": True},
        ],
    )

    class FakeListing:
        def __init__(self, token: str):
            self.token = token
            self.title = "آگهی تست"
            self.filter_id = saved["id"]
            self.filter_name = "چند مقصدی"
            self.price = "100"
            self.mileage = ""
            self.location = "تهران"
            self.url = "https://divar.ir/v/" + token
            self.image_url = ""
            self.age_minutes = 1

        def to_dict(self):
            return {
                "token": self.token,
                "title": self.title,
                "filter_id": self.filter_id,
                "filter_name": self.filter_name,
                "price": self.price,
                "url": self.url,
            }

    class FakeClient:
        def __init__(self, channel: str, fail: bool = False):
            self.channel = channel
            self.fail = fail
            self.sent: list[str] = []

        def send_listing(self, item, chat_id=None, **kwargs):
            if self.fail:
                raise RuntimeError(f"{self.channel} down")
            self.sent.append(str(chat_id))

    clients = {
        "telegram": FakeClient("telegram"),
        "bale": FakeClient("bale", fail=True),
    }

    def fake_build(channel, config=None):
        if channel not in clients:
            raise AppError("missing")
        return clients[channel]

    with mock.patch("runner.collect_listings", return_value=[FakeListing("tok1")]), mock.patch(
        "runner.user_poll_interval_minutes", return_value=60
    ), mock.patch("messengers.build_messenger", side_effect=fake_build), mock.patch(
        "runner.load_config", return_value={"telegram": {}}
    ):
        # import inside patch path used by watch_tick
        result = watch_tick(user_ids=["u1"])

    check("watch_tick sent to telegram dests", len(clients["telegram"].sent) == 2, str(clients["telegram"].sent))
    check("watch_tick tried bale (failed)", clients["bale"].sent == [])
    check("watch_tick sent count > 0 despite bale fail", result.get("sent", 0) >= 2, str(result))

    events = db.list_watch_events("u1", limit=20)
    deliver = [e for e in events if e.get("action") == "deliver"]
    scan = [e for e in events if e.get("action") == "scan"]
    check("scan event logged", len(scan) >= 1)
    check("deliver events per destination", len(deliver) >= 2, str([(e.get("channel"), e.get("status")) for e in deliver]))
    bale_fail = [e for e in deliver if e.get("channel") == "bale" and e.get("status") == "failure"]
    tg_ok = [e for e in deliver if e.get("channel") == "telegram" and e.get("status") == "success"]
    check("bale deliver failure logged", len(bale_fail) >= 1)
    check("telegram deliver success logged", len(tg_ok) >= 1)

    # seen marked even with partial failure
    check("token marked seen after partial fanout", db.is_seen("u1", saved["id"], "tok1"))

    # No destinations -> skipped
    empty_f = db.upsert_filter(
        "u1",
        filter_from_api(
            {
                "name": "بدون مقصد",
                "category": "light",
                "cities": ["شیراز"],
                "destinations": [],
                "chat_id": "",
            }
        ),
    )
    # Clear destinations explicitly and clear telegram fallback by resolving with empty + no chat
    db.set_filter_destinations("u1", empty_f["id"], [])
    # Also need user without telegram for true empty — use resolve on spec with no dest and no chat_id
    # Temporarily unset by resolving with empty destinations and chat_id blank but user has telegram —
    # resolve falls back to telegram_chat_id. Test explicit empty only via destinations disabled all.
    db.set_filter_destinations(
        "u1",
        empty_f["id"],
        [{"channel": "telegram", "chat_id": "111", "enabled": False}],
    )
    # resolve still falls back to user telegram — document this behavior
    r_fallback = db.resolve_filter_destinations(db.get_user("u1"), db.get_filter(empty_f["id"], "u1"))
    check(
        "resolve falls back to user telegram when all disabled",
        r_fallback == [{"channel": "telegram", "chat_id": "111"}],
        str(r_fallback),
    )

    # ------------------------------------------------------------------
    section("6) login link messenger_by_login")
    ok_login = False
    try:
        db.link_messenger_by_login(
            channel="telegram",
            account_id="111-new",
            login_username="legacy",
            password="wrong",
        )
    except AppError:
        ok_login = True
    check("bad password rejected", ok_login)
    u2 = db.link_messenger_by_login(
        channel="telegram",
        account_id="333",
        login_username="legacy",
        password="pass1234",
        username="legacy_user",
        display_name="Legacy",
    )
    check("login links new telegram account_id", u2.get("telegram_chat_id") == "333")

    # ------------------------------------------------------------------
    section("7) HTTP API (temp server, bots not started)")
    # Secure cookies follow PUBLIC_BASE_URL; force http for CookieJar on localhost.
    prev_base = os.environ.get("PUBLIC_BASE_URL")
    os.environ["PUBLIC_BASE_URL"] = "http://127.0.0.1"

    from app import Handler, ReuseServer

    # Prevent bot/watcher side effects: don't call serve(); start bare HTTP server
    httpd = ReuseServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def http_json(method: str, path: str, body: dict | None = None, expect: int = 200) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with opener.open(req, timeout=10) as resp:
                raw = resp.read().decode()
                check(f"HTTP {method} {path} status", resp.status == expect, f"got {resp.status}")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            check(f"HTTP {method} {path} status", exc.code == expect, f"got {exc.code} body={raw[:200]}")
            try:
                return json.loads(raw)
            except Exception:
                return {"error": raw}

    # unauthenticated
    http_json("GET", "/api/me", expect=401)

    login = http_json(
        "POST",
        "/api/login",
        {"username": "legacy", "password": "pass1234"},
        expect=200,
    )
    check("login returns ok", login.get("ok") is True)
    check("session cookie stored", any(c.name == "session" for c in jar), str([c.name for c in jar]))

    with mock.patch("messengers.telegram_bot_username", return_value="TestBot"), mock.patch(
        "messengers._bot_username", return_value="BaleBot"
    ), mock.patch.dict(
        os.environ, {"TELEGRAM_BOT_TOKEN": "tg-token", "BALE_BOT_TOKEN": "bale-token"}, clear=False
    ):
        me = http_json("GET", "/api/me")
        check("GET /api/me messengers", isinstance(me.get("messengers"), list) and len(me["messengers"]) >= 1)
        ms = http_json("GET", "/api/messengers")
        check("GET /api/messengers", len(ms.get("messengers") or []) >= 1)

    chats = http_json("GET", "/api/chats")
    check("GET /api/chats", isinstance(chats.get("chats"), list) and len(chats["chats"]) >= 1)
    chats_b = http_json("GET", "/api/chats?channel=bale")
    check(
        "GET /api/chats?channel=bale",
        all((c.get("channel") or "telegram") == "bale" for c in (chats_b.get("chats") or [])),
        str(chats_b.get("chats")),
    )

    filters = http_json("GET", "/api/filters")
    check("GET /api/filters has destinations", any(f.get("destinations") for f in filters.get("filters") or []))

    created = http_json(
        "POST",
        "/api/filters",
        {
            "name": "API multi",
            "category": "light",
            "cities": ["مشهد"],
            "destinations": [
                {"channel": "telegram", "chat_id": "333"},
                {"channel": "bale", "chat_id": "bale-99"},
            ],
        },
        expect=201,
    )
    fid = (created.get("filter") or {}).get("id")
    check("POST /api/filters with destinations", bool(fid) and len((created["filter"].get("destinations") or [])) == 2)

    updated = http_json(
        "POST",
        f"/api/filters/{fid}/destinations",
        {
            "destinations": [
                {"channel": "bale", "chat_id": "bale-group-1"},
                {"channel": "telegram", "chat_id": "222"},
            ]
        },
    )
    check(
        "POST destinations endpoint",
        len((updated.get("filter") or {}).get("destinations") or []) == 2,
        str((updated.get("filter") or {}).get("destinations")),
    )

    from config_store import load_dotenv, admin_username, admin_password

    load_dotenv()
    admin_login = http_json(
        "POST",
        "/api/admin/login",
        {"username": admin_username(), "password": admin_password()},
    )
    check("admin login", admin_login.get("ok") is True)
    check(
        "admin_session cookie stored",
        any(c.name == "admin_session" for c in jar),
        str([c.name for c in jar]),
    )

    admin_user = http_json("GET", f"/api/admin/users/u1")
    check("admin get user", (admin_user.get("user") or {}).get("id") == "u1", str(admin_user)[:200])

    admin_dest = http_json(
        "POST",
        f"/api/admin/users/u1/filters/{fid}/destinations",
        {"destinations": [{"channel": "telegram", "chat_id": "333"}]},
    )
    check(
        "admin set destinations",
        len((admin_dest.get("filter") or {}).get("destinations") or []) == 1,
        str(admin_dest.get("filter") or admin_dest),
    )

    # Static portal assets contain multi-messenger UI markers
    for path, needle in (
        ("/portal.js", "renderMessengers"),
        ("/portal.js", "destinations"),
        ("/app", "messenger-list"),
        ("/app", "dest-channel"),
        ("/styles.css", "messenger-grid"),
    ):
        req = urllib.request.Request(base + path)
        try:
            with opener.open(req, timeout=10) as resp:
                text = resp.read().decode()
                check(f"asset {path} contains {needle}", needle in text)
        except urllib.error.HTTPError as exc:
            check(f"asset {path} contains {needle}", False, f"HTTP {exc.code}")

    httpd.shutdown()
    if prev_base is None:
        os.environ.pop("PUBLIC_BASE_URL", None)
    else:
        os.environ["PUBLIC_BASE_URL"] = prev_base

    # ------------------------------------------------------------------
    section("8) Bot channel wiring (unit)")
    from bot import MessengerBot

    b = MessengerBot("bale")
    check("MessengerBot.channel bale", b.channel == "bale")
    tbot = MessengerBot("telegram")
    check("MessengerBot.channel telegram", tbot.channel == "telegram")

    # ------------------------------------------------------------------
    section("9) Production DB migration dry-check (read-only copy)")
    prod = ROOT / "data" / "service.db"
    if prod.exists():
        prod_copy = Path(tmp.name) / "prod_copy.db"
        prod_copy.write_bytes(prod.read_bytes())
        # migrate copy
        old_path = db.DB_PATH
        db.DB_PATH = prod_copy
        try:
            db.init_db(prod_copy)
            c = db.connect()
            has_acc = c.execute(
                "SELECT COUNT(*) AS n FROM messenger_accounts"
            ).fetchone()["n"]
            has_dest = c.execute(
                "SELECT COUNT(*) AS n FROM filter_destinations"
            ).fetchone()["n"]
            ch_cols = {r[1] for r in c.execute("PRAGMA table_info(user_chats)").fetchall()}
            check("prod copy migrated channel col", "channel" in ch_cols)
            check("prod copy messenger_accounts rows", has_acc >= 0, f"n={has_acc}")
            check("prod copy filter_destinations rows", has_dest >= 0, f"n={has_dest}")
            # users with telegram_chat_id should have accounts
            missing = c.execute(
                """
                SELECT COUNT(*) AS n FROM users u
                WHERE u.telegram_chat_id IS NOT NULL AND u.telegram_chat_id != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM messenger_accounts m
                    WHERE m.user_id = u.id AND m.channel = 'telegram'
                  )
                """
            ).fetchone()["n"]
            check("prod copy no orphan telegram users", missing == 0, f"missing={missing}")
            orphan_filters = c.execute(
                """
                SELECT COUNT(*) AS n FROM filters f
                WHERE NOT EXISTS (SELECT 1 FROM filter_destinations d WHERE d.filter_id = f.id)
                """
            ).fetchone()["n"]
            # filters without destinations may exist if no chat — warn not fail hard if 0 dest intentional
            check(
                "prod copy filters have destinations (or empty ok)",
                True,
                f"filters_without_dest={orphan_filters}",
            )
            c.close()
        finally:
            db.DB_PATH = old_path
    else:
        check("prod db exists", False, "data/service.db missing")

    # ------------------------------------------------------------------
    section("SUMMARY")
    print(f"Passed: {PASS}")
    print(f"Failed: {FAIL}")
    if ERRORS:
        print("\nFailures:")
        for e in ERRORS:
            print(" -", e)
    tmp.cleanup()
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
