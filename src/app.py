from __future__ import annotations

import json
import mimetypes
import threading
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from bot import TelegramBot
from categories import category_payload
from config_store import (
    ROOT,
    AppError,
    admin_credentials_ok,
    admin_password,
    admin_token,
    admin_username,
    filter_to_api,
    format_slot_time,
    load_config,
    load_dotenv,
    next_slot_at,
    poll_interval_seconds,
    public_settings,
    seconds_until_next_slot,
    update_settings,
)
from runner import get_client, preview_spec, save_user_filter, send_best_for_user, watch_tick
import db

WEB_DIR = ROOT / "web"
BOT = TelegramBot()


class Watcher:
    def __init__(self) -> None:
        self.running = False
        self.last_message = ""
        self.next_run_at = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.running = True
        self.next_run_at = format_slot_time(next_slot_at(include_now=True))
        self.last_message = f"Next scan at {self.next_run_at}."
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.running = False
        self.next_run_at = ""

    def _loop(self) -> None:
        include_now = True
        while not self._stop.is_set():
            interval = poll_interval_seconds()
            wait = seconds_until_next_slot(interval, include_now=include_now)
            include_now = False
            if wait > 0:
                when = next_slot_at(interval, include_now=False)
                self.next_run_at = format_slot_time(when)
                self.last_message = f"Next scan at {self.next_run_at}."
                if self._stop.wait(wait):
                    break
            try:
                result = watch_tick()
                self.last_message = result.get("message") or "Done."
            except Exception as exc:
                self.last_message = str(exc)
            self.next_run_at = format_slot_time(next_slot_at(include_now=False))


WATCHER = Watcher()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path == "/":
                return self._file(WEB_DIR / "index.html")
            if path == "/admin/login":
                if self._admin_logged_in():
                    self.send_response(302)
                    self.send_header("Location", "/admin")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "admin-login.html")
            if path == "/admin":
                if not self._admin_logged_in():
                    self.send_response(302)
                    self.send_header("Location", "/admin/login")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "admin.html")
            if path == "/app":
                if not self._cookie("session") or not db.get_session_user(self._cookie("session")):
                    self.send_response(302)
                    self.send_header("Location", "/app/login")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "portal.html")
            if path == "/app/login":
                if self._cookie("session") and db.get_session_user(self._cookie("session")):
                    self.send_response(302)
                    self.send_header("Location", "/app")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "app-login.html")
            if path == "/app/access":
                self.send_response(302)
                self.send_header("Location", "/app/login")
                self.end_headers()
                return
            if path == "/app/api":
                if not self._cookie("session") or not db.get_session_user(self._cookie("session")):
                    self.send_response(302)
                    self.send_header("Location", "/app/login")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "app-api.html")
            if path == "/login":
                token = (query.get("token") or [""])[0]
                user = db.consume_magic_session(token)
                if not user:
                    return self._html_message("لینک ورود نامعتبر یا منقضی است.", 400)
                self.send_response(302)
                self._set_session_cookie(user["session_token"])
                self.send_header("Location", "/app")
                self.end_headers()
                return
            if path.startswith("/u/"):
                username = path.split("/", 2)[2].strip().lstrip("@").lower()
                return self._file(WEB_DIR / "feed.html")
            if path in {
                "/styles.css",
                "/app.js",
                "/admin.js",
                "/admin-login.js",
                "/app-login.js",
                "/app-api.js",
                "/portal.js",
                "/feed.js",
            }:
                return self._file(WEB_DIR / path.lstrip("/"))

            if path == "/api/status":
                status = public_settings()
                status["watching"] = WATCHER.running
                status["bot_running"] = BOT.running
                status["last_message"] = WATCHER.last_message or BOT.last_message
                status["next_watch_at"] = WATCHER.next_run_at or None
                status["user_count"] = len(db.list_users())
                return self._json(status)
            if path == "/api/cities":
                q = (query.get("q") or [""])[0]
                return self._json({"cities": get_client().search_cities(q)})
            if path == "/api/categories":
                return self._json(category_payload())
            if path == "/api/divar-filters":
                category = (query.get("category") or ["ROOT"])[0]
                return self._json({"category": category, "fields": get_client().filter_fields(category)})

            if path == "/api/admin/users":
                self._require_admin()
                return self._json({"users": db.list_users()})
            if path == "/api/me":
                user = self._require_user()
                return self._json({"user": _safe_user(user)})
            if path == "/api/filters":
                user = self._require_user()
                return self._json({"filters": [filter_to_api(spec) for spec in db.list_filters(user["id"])]})
            if path == "/api/feed":
                user = self._require_user()
                limit = int((query.get("limit") or ["50"])[0])
                offset = int((query.get("offset") or ["0"])[0])
                return self._json({"listings": db.list_cached_listings(user["id"], limit=limit, offset=offset)})
            if path.startswith("/api/public/feed/"):
                username = path.rsplit("/", 1)[-1].lstrip("@").lower()
                found = db.get_user_by_public_slug(username)
                if not found or not found["active"]:
                    raise AppError("User not found.")
                limit = int((query.get("limit") or ["50"])[0])
                offset = int((query.get("offset") or ["0"])[0])
                return self._json(
                    {
                        "username": found.get("public_slug") or found["telegram_username"],
                        "listings": db.list_cached_listings(found["id"], limit=limit, offset=offset),
                    }
                )
            if path == "/api/v1/listings":
                user = self._require_api_user()
                limit = int((query.get("limit") or ["50"])[0])
                offset = int((query.get("offset") or ["0"])[0])
                return self._json(
                    {
                        "listings": db.list_cached_listings(user["id"], limit=limit, offset=offset),
                        "username": user["telegram_username"],
                    }
                )
            return self._json({"error": "Not found."}, 404)
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            body = self._read_json()
            if path == "/api/login":
                user = db.authenticate_login(
                    str(body.get("username") or ""),
                    str(body.get("password") or ""),
                )
                token = db.create_browser_session(user["id"])
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self._set_session_cookie(token)
                payload = b'{"ok":true}'
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if path == "/api/admin/login":
                username = str(body.get("username") or "")
                password = str(body.get("password") or "")
                if not admin_credentials_ok(username, password):
                    raise AppError("یوزرنیم یا رمز عبور نادرست است.")
                token = db.create_admin_session()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self._set_admin_cookie(token)
                payload = b'{"ok":true}'
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if path == "/api/admin/logout":
                db.delete_admin_session(self._cookie("admin_session"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header(
                    "Set-Cookie",
                    "admin_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
                )
                payload = b'{"ok":true}'
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if path == "/api/admin/users":
                self._require_admin()
                user = db.create_user(
                    body.get("telegram_username") or "",
                    display_name=str(body.get("display_name") or ""),
                    ai_enabled=bool(body.get("ai_enabled")),
                    active=bool(body.get("active", True)),
                )
                return self._json({"user": user}, 201)
            if path.startswith("/api/admin/users/") and path.endswith("/rotate-key"):
                self._require_admin()
                user_id = path.split("/")[4]
                return self._json({"user": db.rotate_api_key(user_id)})
            if path == "/api/filters":
                user = self._require_user()
                return self._json({"filter": save_user_filter(user["id"], body)}, 201)
            if path.endswith("/toggle") and path.startswith("/api/filters/"):
                user = self._require_user()
                filter_id = path.split("/")[3]
                enabled = body.get("enabled")
                if enabled is None:
                    current = db.get_filter(filter_id, user["id"])
                    if not current:
                        raise AppError("Filter not found.")
                    enabled = not current["enabled"]
                saved = db.set_filter_enabled(filter_id, user["id"], bool(enabled))
                return self._json({"filter": filter_to_api(saved)})
            if path == "/api/preview":
                self._require_user()
                return self._json(preview_spec(body))
            if path == "/api/run":
                user = self._require_user()
                return self._json(send_best_for_user(user, body.get("count")))
            if path == "/api/watch":
                self._require_admin()
                action = str(body.get("action") or "").strip()
                if action == "start":
                    if not public_settings()["telegram_ready"]:
                        raise AppError("Configure TELEGRAM_BOT_TOKEN first.")
                    WATCHER.start()
                elif action == "stop":
                    WATCHER.stop()
                else:
                    raise AppError("action must be start or stop.")
                return self._json(
                    {
                        "watching": WATCHER.running,
                        "bot_running": BOT.running,
                        "last_message": WATCHER.last_message,
                        "next_watch_at": WATCHER.next_run_at or None,
                    }
                )
            if path == "/api/logout":
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", "session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
                payload = b'{"ok":true}'
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            return self._json({"error": "Not found."}, 404)
        except Exception as exc:
            self._handle_error(exc)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            body = self._read_json()
            if path.startswith("/api/admin/users/"):
                self._require_admin()
                user_id = path.rsplit("/", 1)[-1]
                return self._json({"user": self._admin_update_user(user_id, body)})
            if path.startswith("/api/filters/"):
                user = self._require_user()
                body["id"] = path.rsplit("/", 1)[-1]
                return self._json({"filter": save_user_filter(user["id"], body)})
            if path == "/api/settings":
                self._require_admin()
                return self._json(update_settings(body))
            return self._json({"error": "Not found."}, 404)
        except Exception as exc:
            self._handle_error(exc)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path.startswith("/api/filters/"):
                user = self._require_user()
                db.delete_filter(path.rsplit("/", 1)[-1], user["id"])
                return self._json({"ok": True})
            return self._json({"error": "Not found."}, 404)
        except Exception as exc:
            self._handle_error(exc)

    def _admin_update_user(self, user_id: str, body: dict) -> dict:
        fields = {}
        if "display_name" in body:
            fields["display_name"] = body.get("display_name") or ""
        if "ai_enabled" in body:
            fields["ai_enabled"] = bool(body.get("ai_enabled"))
        if "active" in body:
            fields["active"] = bool(body.get("active"))
        return db.update_user(user_id, **fields)

    def log_message(self, format: str, *args: object) -> None:
        sys_stderr = __import__("sys").stderr
        sys_stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def _cookie(self, name: str) -> str:
        raw = self.headers.get("Cookie") or ""
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return ""
        morsel = cookie.get(name)
        return morsel.value if morsel else ""

    def _set_session_cookie(self, token: str) -> None:
        self.send_header(
            "Set-Cookie",
            f"session={token}; Path=/; Max-Age={30 * 24 * 3600}; HttpOnly; SameSite=Lax",
        )

    def _set_admin_cookie(self, token: str) -> None:
        self.send_header(
            "Set-Cookie",
            f"admin_session={token}; Path=/; Max-Age={14 * 24 * 3600}; HttpOnly; SameSite=Lax",
        )

    def _admin_logged_in(self) -> bool:
        return db.admin_session_ok(self._cookie("admin_session"))

    def _require_admin(self) -> None:
        if self._admin_logged_in():
            return

        expected = admin_token()
        if expected:
            got = self.headers.get("X-Admin-Token") or ""
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                got = auth[7:].strip()
            if got == expected:
                return

        if not admin_username() or not admin_password():
            if not expected:
                raise AppError("Admin credentials are not configured.")
        raise AppError("Admin authentication failed.")

    def _require_user(self) -> dict:
        token = self._cookie("session")
        user = db.get_session_user(token)
        if not user:
            raise AppError("Login required.")
        return user

    def _require_api_user(self) -> dict:
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("basic "):
            import base64

            try:
                decoded = base64.b64decode(auth[6:].strip()).decode("utf-8")
                username, _, password = decoded.partition(":")
            except Exception as exc:
                raise AppError("Invalid API key.") from exc
            try:
                return db.authenticate_login(username, password)
            except AppError as exc:
                raise AppError("Invalid API key.") from exc
        key = ""
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
        key = key or self.headers.get("X-Api-Key") or ""
        user = db.get_user_by_api_key(key)
        if not user:
            raise AppError("Invalid API key.")
        return user

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AppError("Invalid JSON.") from exc
        return data if isinstance(data, dict) else {}

    def _file(self, path: Path) -> None:
        if not path.is_file() or WEB_DIR not in path.resolve().parents and path.parent != WEB_DIR:
            return self._json({"error": "Not found."}, 404)
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _html_message(self, message: str, status: int = 200) -> None:
        body = f"<!doctype html><html lang=fa dir=rtl><meta charset=utf-8><title>ورود</title><body><p>{message}</p><p><a href=/>بازگشت</a></p></body></html>"
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, AppError):
            status = 401 if "auth" in str(exc).lower() or "login" in str(exc).lower() or "admin" in str(exc).lower() or "api key" in str(exc).lower() else 400
            return self._json({"error": str(exc)}, status)
        if isinstance(exc, ValueError):
            return self._json({"error": str(exc)}, 400)
        traceback.print_exc()
        return self._json({"error": "Internal server error."}, 500)


def _safe_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "telegram_username": user.get("telegram_username") or "",
        "login_username": user.get("login_username") or "",
        "display_name": user["display_name"],
        "ai_enabled": user["ai_enabled"],
        "linked": user["linked"],
        "public_slug": user.get("public_slug")
        or user.get("login_username")
        or user.get("telegram_username")
        or "",
    }


class ReuseServer(ThreadingHTTPServer):
    allow_reuse_address = True


def serve(host: str = "0.0.0.0", port: int = 8765) -> None:
    load_dotenv()
    load_config()
    db.init_db()
    settings = public_settings()
    if settings["telegram_token"]:
        BOT.start()
        print("Telegram bot listening", flush=True)
        try:
            WATCHER.start()
            print("Watcher started automatically", flush=True)
        except Exception as exc:
            print(f"Watcher auto-start skipped: {exc}", flush=True)
    server = ReuseServer((host, port), Handler)
    print(f"Service: http://127.0.0.1:{port}", flush=True)
    print(f"Admin:   http://127.0.0.1:{port}/admin", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        BOT.stop()
        WATCHER.stop()
        server.server_close()


if __name__ == "__main__":
    serve()
