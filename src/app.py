from __future__ import annotations

import json
import mimetypes
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from config_store import (
    ROOT,
    AppError,
    delete_filter,
    detect_telegram_chat,
    filter_to_api,
    format_slot_time,
    load_config,
    load_dotenv,
    next_slot_at,
    poll_interval_seconds,
    public_settings,
    seconds_until_next_slot,
    toggle_filter,
    update_settings,
    upsert_filter,
)
from runner import get_client, preview_spec, send_best, watch_tick
from bot import TelegramBot

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
            if path in {"/styles.css", "/app.js"}:
                return self._file(WEB_DIR / path.lstrip("/"))
            if path == "/api/filters":
                config = load_config()
                return self._json(
                    {"filters": [filter_to_api(spec) for spec in config.get("filters") or []]}
                )
            if path == "/api/status":
                status = public_settings()
                status["watching"] = WATCHER.running
                status["bot_running"] = BOT.running
                status["last_message"] = WATCHER.last_message or BOT.last_message
                status["next_watch_at"] = WATCHER.next_run_at or None
                return self._json(status)
            if path == "/api/cities":
                q = (query.get("q") or [""])[0]
                cities = get_client().search_cities(q)
                return self._json({"cities": cities})
            return self._json({"error": "Not found."}, 404)
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            body = self._read_json()
            if path == "/api/filters":
                return self._json({"filter": upsert_filter(body)}, 201)
            if path.endswith("/toggle") and path.startswith("/api/filters/"):
                filter_id = path.split("/")[3]
                return self._json({"filter": toggle_filter(filter_id, body.get("enabled"))})
            if path == "/api/preview":
                return self._json(preview_spec(body))
            if path == "/api/run":
                return self._json(send_best(body.get("count")))
            if path == "/api/watch":
                action = str(body.get("action") or "").strip()
                if action == "start":
                    if not public_settings()["telegram_ready"]:
                        raise AppError("Configure Telegram in .env first.")
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
            if path == "/api/telegram/detect-chat":
                result = detect_telegram_chat(body.get("chat_id"))
                result["status"] = public_settings()
                return self._json(result)
            return self._json({"error": "Not found."}, 404)
        except Exception as exc:
            self._handle_error(exc)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            body = self._read_json()
            if path.startswith("/api/filters/"):
                body["id"] = path.rsplit("/", 1)[-1]
                return self._json({"filter": upsert_filter(body)})
            if path == "/api/settings":
                return self._json(update_settings(body))
            return self._json({"error": "Not found."}, 404)
        except Exception as exc:
            self._handle_error(exc)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path.startswith("/api/filters/"):
                delete_filter(path.rsplit("/", 1)[-1])
                return self._json({"ok": True})
            return self._json({"error": "Not found."}, 404)
        except Exception as exc:
            self._handle_error(exc)

    def log_message(self, format: str, *args: object) -> None:
        sys_stderr = __import__("sys").stderr
        sys_stderr.write("%s - %s\n" % (self.address_string(), format % args))

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

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, AppError):
            return self._json({"error": str(exc)}, 400)
        if isinstance(exc, ValueError):
            return self._json({"error": str(exc)}, 400)
        traceback.print_exc()
        return self._json({"error": "Internal server error."}, 500)


class ReuseServer(ThreadingHTTPServer):
    allow_reuse_address = True


def serve(host: str = "0.0.0.0", port: int = 8765) -> None:
    load_dotenv()
    load_config()
    if public_settings()["telegram_ready"]:
        BOT.start()
        print("Telegram bot listening for /best", flush=True)
    server = ReuseServer((host, port), Handler)
    print(f"Filter page: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        BOT.stop()
        WATCHER.stop()
        server.server_close()


if __name__ == "__main__":
    serve()
