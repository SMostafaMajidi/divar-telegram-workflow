from __future__ import annotations

import json
import mimetypes
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from config_store import (
    AppError,
    delete_filter,
    detect_telegram_chat,
    filter_to_api,
    load_config,
    load_dotenv,
    poll_interval_seconds,
    public_settings,
    toggle_filter,
    update_settings,
    upsert_filter,
)
from runner import get_client, preview_spec, run_filters

WEB_DIR = Path(__file__).resolve().parent / "web"


class Watcher:
    def __init__(self) -> None:
        self.running = False
        self.last_message = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.running = False

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                result = run_filters(dry_run=False)
                self.last_message = result.get("message") or "Done."
            except Exception as exc:
                self.last_message = str(exc)
            interval = poll_interval_seconds()
            if self._stop.wait(interval):
                break


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
                status["last_message"] = WATCHER.last_message
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
                ids = body.get("ids") or None
                dry_run = bool(body.get("dry_run"))
                return self._json(run_filters(ids, dry_run=dry_run))
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
                        "last_message": WATCHER.last_message,
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
    server = ReuseServer((host, port), Handler)
    print(f"Filter page: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


if __name__ == "__main__":
    serve()
