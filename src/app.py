from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from bot import MessengerBot
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
    next_due_watch_users,
    next_slot_at,
    poll_interval_minutes,
    public_base_url,
    public_settings,
    payment_info,
    upsert_env_value,
    slot_preview_minutes,
    update_settings,
    user_best_count,
    user_poll_interval_minutes,
    user_poll_offset_minutes,
)
from runner import get_client, preview_spec, save_user_filter, send_best_for_user, watch_tick
from plans import has_api_access
import db

WEB_DIR = ROOT / "web"
BOT = MessengerBot("telegram")
BALE_BOT = MessengerBot("bale")
BOTS = (BOT, BALE_BOT)


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

    def _watchable_users(self) -> list[dict]:
        return [bundle["user"] for bundle in db.active_users_with_filters()]

    def _loop(self) -> None:
        include_now = True
        while not self._stop.is_set():
            users = self._watchable_users()
            due, wait, when = next_due_watch_users(users, include_now=include_now)
            include_now = False
            if wait > 0:
                self.next_run_at = format_slot_time(when)
                self.last_message = f"Next scan at {self.next_run_at}."
                # Sleep toward a fixed deadline. Do NOT recompute wait with
                # include_now=False after landing on the slot — that skips it.
                deadline = time.monotonic() + float(wait)
                while not self._stop.is_set():
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    if self._stop.wait(min(left, 15.0)):
                        return
                if self._stop.is_set():
                    break
                users = self._watchable_users()
                due, _, when = next_due_watch_users(users, include_now=True)
            if not due:
                if self._stop.wait(5.0):
                    break
                continue
            try:
                result = watch_tick(user_ids=[user["id"] for user in due])
                self.last_message = result.get("message") or "Done."
            except Exception as exc:
                self.last_message = str(exc)
            _, _, next_when = next_due_watch_users(self._watchable_users(), include_now=False)
            self.next_run_at = format_slot_time(next_when) if next_when else ""
            # Avoid double-firing the same second.
            if self._stop.wait(1.0):
                break


WATCHER = Watcher()


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        self.close_connection = True
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        if path in {
            "/",
            "/admin",
            "/admin/login",
            "/admin/settings",
            "/pricing",
            "/terms",
            "/cancel-policy",
            "/support",
            "/app",
            "/app/login",
            "/app/access",
            "/app/api",
            "/app/billing",
            "/admin/payments",
            "/admin/plans",
            "/admin/payment-settings",
            "/styles.css",
            "/app.js",
            "/admin.js",
            "/admin-common.js",
            "/admin-settings.js",
            "/admin-user.js",
            "/admin-payments.js",
            "/admin-plans.js",
            "/admin-payment-settings.js",
            "/admin-login.js",
            "/app-login.js",
            "/app-api.js",
            "/portal.js",
            "/billing.js",
            "/bank-card.js",
            "/feed.js",
            "/dates.js",
        } or path.startswith("/u/") or path.startswith("/admin/users/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        if path.startswith("/api/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path != "/" and path.endswith("/"):
            target = path.rstrip("/") or "/"
            if parsed.query:
                target = f"{target}?{parsed.query}"
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        query = parse_qs(parsed.query)
        try:
            if path == "/":
                if self._cookie("session") and db.get_session_user(self._cookie("session")):
                    self.send_response(302)
                    self.send_header("Location", "/app")
                    self.end_headers()
                    return
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
            if path == "/admin/settings":
                if not self._admin_logged_in():
                    self.send_response(302)
                    self.send_header("Location", "/admin/login")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "admin-settings.html")
            if path == "/pricing":
                return self._file(WEB_DIR / "pricing.html")
            if path == "/terms":
                return self._file(WEB_DIR / "terms.html")
            if path == "/cancel-policy":
                return self._file(WEB_DIR / "cancel-policy.html")
            if path == "/support":
                return self._file(WEB_DIR / "support.html")
            if path == "/admin/payments":
                if not self._admin_logged_in():
                    self.send_response(302)
                    self.send_header("Location", "/admin/login")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "admin-payments.html")
            if path == "/admin/plans":
                if not self._admin_logged_in():
                    self.send_response(302)
                    self.send_header("Location", "/admin/login")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "admin-plans.html")
            if path == "/admin/payment-settings":
                if not self._admin_logged_in():
                    self.send_response(302)
                    self.send_header("Location", "/admin/login")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "admin-payment-settings.html")
            if path.startswith("/admin/users/"):
                if not self._admin_logged_in():
                    self.send_response(302)
                    self.send_header("Location", "/admin/login")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "admin-user.html")
            if path == "/app":
                if not self._cookie("session") or not db.get_session_user(self._cookie("session")):
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "portal.html")
            if path == "/app/chats":
                if not self._cookie("session") or not db.get_session_user(self._cookie("session")):
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "chats.html")
            if path == "/app/billing":
                if not self._cookie("session") or not db.get_session_user(self._cookie("session")):
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                return self._file(WEB_DIR / "billing.html")
            if path == "/app/login":
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if path == "/app/access":
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if path == "/app/api":
                user = db.get_session_user(self._cookie("session"))
                if not user:
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                if not has_api_access(user):
                    self.send_response(302)
                    self.send_header("Location", "/pricing")
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
                "/admin-common.js",
                "/admin-settings.js",
                "/admin-user.js",
                "/admin-login.js",
                "/app-login.js",
                "/app-api.js",
                "/portal.js",
                "/chats.js",
                "/billing.js",
                "/bank-card.js",
                "/feed.js",
                "/dates.js",
                "/admin-payments.js",
                "/admin-plans.js",
                "/admin-payment-settings.js",
            }:
                return self._file(WEB_DIR / path.lstrip("/"))

            if path == "/api/status":
                status = public_settings()
                status["watching"] = WATCHER.running
                status["bot_running"] = any(bot.running for bot in BOTS)
                status["bots"] = {bot.channel: bot.running for bot in BOTS}
                status["last_message"] = WATCHER.last_message or next(
                    (bot.last_message for bot in BOTS if bot.last_message), ""
                )
                status["next_watch_at"] = WATCHER.next_run_at or None
                status["user_count"] = len(db.list_users())
                return self._json(status)
            if path == "/api/cities":
                q = (query.get("q") or [""])[0]
                return self._json({"cities": get_client().search_cities(q)})
            if path == "/api/plans":
                from plans import list_plans

                return self._json({"plans": list_plans(), "payment": payment_info()})
            if path == "/api/admin/plans":
                self._require_admin()
                from plans import list_plans

                return self._json({"plans": list_plans(include_inactive=True)})
            if path == "/api/payment-info":
                return self._json({"payment": payment_info()})
            if path == "/api/admin/payment-settings":
                self._require_admin()
                return self._json({"payment": payment_info()})
            if path == "/api/invoices":
                user = self._require_user()
                return self._json({"invoices": db.list_user_invoices(user["id"])})
            if path == "/api/admin/invoices":
                self._require_admin()
                status = (query.get("status") or [""])[0].strip() or None
                return self._json({"invoices": db.list_invoices(status=status)})
            if path.startswith("/api/invoices/") and path.endswith("/receipt"):
                parts = path.strip("/").split("/")
                if len(parts) != 4:
                    raise AppError("Not found.")
                invoice_id = parts[2]
                invoice = db.get_invoice(invoice_id)
                if not invoice:
                    raise AppError("فاکتور پیدا نشد.")
                user = None
                try:
                    user = self._require_user()
                except AppError:
                    user = None
                if user and user["id"] == invoice["user_id"]:
                    pass
                elif self._admin_logged_in():
                    pass
                else:
                    raise AppError("Login required.")
                file_info = db.invoice_receipt_file(invoice_id)
                if not file_info:
                    raise AppError("فیشی آپلود نشده.")
                path_file, mime, download_name = file_info
                payload = path_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Content-Disposition", f'inline; filename="{download_name}"')
                self.send_header("Cache-Control", "private, no-cache")
                self.end_headers()
                self.wfile.write(payload)
                return
            if path == "/api/categories":
                return self._json(category_payload())
            if path == "/api/divar-filters":
                category = (query.get("category") or ["ROOT"])[0]
                return self._json({"category": category, "fields": get_client().filter_fields(category)})

            if path == "/api/admin/users":
                self._require_admin()
                return self._json({"users": [_admin_user(user) for user in db.list_users()]})
            if path.startswith("/api/admin/users/"):
                self._require_admin()
                parts = path.strip("/").split("/")
                # api/admin/users/{id}
                # api/admin/users/{id}/chats
                # api/admin/users/{id}/filters
                if len(parts) < 4:
                    raise AppError("User not found.")
                user_id = parts[3]
                found = db.get_user(user_id)
                if not found:
                    raise AppError("User not found.")
                if len(parts) == 4:
                    return self._json({"user": _admin_user(found)})
                if len(parts) == 5 and parts[4] == "chats":
                    return self._json({"chats": db.list_user_chats(user_id)})
                if len(parts) == 5 and parts[4] == "filters":
                    return self._json(
                        {"filters": [filter_to_api(spec) for spec in db.list_filters(user_id)]}
                    )
                if len(parts) == 5 and parts[4] == "invoices":
                    return self._json({"invoices": db.list_user_invoices(user_id, limit=50)})
                if len(parts) == 5 and parts[4] == "watch-events":
                    limit = int((query.get("limit") or ["50"])[0])
                    return self._json({"events": db.list_watch_events(user_id, limit=limit)})
                if len(parts) == 5 and parts[4] == "tickets":
                    status = (query.get("status") or [""])[0].strip() or None
                    return self._json({"tickets": db.list_user_tickets(user_id, status=status)})
                if len(parts) == 5 and parts[4] == "eitaa":
                    return self._json(_eitaa_payload(user_id))
                if len(parts) == 6 and parts[4] == "tickets":
                    ticket = db.get_ticket(parts[5], user_id)
                    if not ticket:
                        raise AppError("تیکت پیدا نشد.")
                    return self._json({"ticket": ticket})
                raise AppError("Not found.")
            if path == "/api/me":
                user = self._require_user()
                from messengers import public_messenger_payload

                return self._json(
                    {
                        "user": _safe_user(user),
                        "messengers": public_messenger_payload(user),
                    }
                )
            if path == "/api/messengers":
                user = self._require_user()
                from messengers import public_messenger_payload

                return self._json({"messengers": public_messenger_payload(user)})
            if path == "/api/eitaa":
                user = self._require_user()
                return self._json(_eitaa_payload(user["id"]))
            if path == "/api/tickets":
                user = self._require_user()
                status = (query.get("status") or [""])[0].strip() or None
                return self._json({"tickets": db.list_user_tickets(user["id"], status=status)})
            if path.startswith("/api/tickets/"):
                user = self._require_user()
                ticket_id = path.strip("/").split("/")[2]
                ticket = db.get_ticket(ticket_id, user["id"])
                if not ticket:
                    raise AppError("تیکت پیدا نشد.")
                return self._json({"ticket": ticket})
            if path == "/api/chats":
                user = self._require_user()
                channel = (query.get("channel") or [""])[0].strip() or None
                return self._json({"chats": db.list_user_chats(user["id"], channel=channel)})
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
                if not has_api_access(user):
                    raise AppError("API access is available on the Pro plan only.")
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
            ctype = (self.headers.get("Content-Type") or "").lower()
            body: dict = {}
            if "multipart/form-data" not in ctype:
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
                    f"admin_session=; Path=/; Max-Age=0; {self._cookie_flags()}",
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
                return self._json({"user": _admin_user(user)}, 201)
            if path == "/api/admin/plans":
                self._require_admin()
                create = bool(body.get("create"))
                plan = db.upsert_plan(body, create=create)
                from plans import format_toman

                plan = dict(plan)
                plan["price_label"] = format_toman(plan.get("price_toman"))
                return self._json({"plan": plan}, 201 if create else 200)
            if path == "/api/admin/payment-settings":
                self._require_admin()
                upsert_env_value("PAYMENT_CARD_NUMBER", str(body.get("card_number") or "").strip())
                upsert_env_value("PAYMENT_CARD_HOLDER", str(body.get("card_holder") or "").strip())
                upsert_env_value("PAYMENT_BANK_NAME", str(body.get("bank_name") or "").strip())
                sheba = str(body.get("sheba") or "").strip().replace(" ", "").upper()
                upsert_env_value("PAYMENT_SHEBA", sheba)
                upsert_env_value("SUPPORT_TELEGRAM", str(body.get("support_telegram") or "").strip().lstrip("@"))
                upsert_env_value("PAYMENT_NOTE", str(body.get("note") or "").strip())
                return self._json({"payment": payment_info(), "ok": True})
            if path == "/api/invoices":
                user = self._require_user()
                invoice = db.create_invoice(user["id"], str(body.get("plan_id") or ""))
                return self._json({"invoice": invoice, "payment": payment_info()}, 201)
            if path == "/api/eitaa":
                user = self._require_user()
                return self._json(_save_eitaa_token(user["id"], body))
            if path == "/api/eitaa/channels":
                user = self._require_user()
                return self._json(_add_eitaa_channel(user["id"], body), 201)
            if path.startswith("/api/admin/users/") and path.endswith("/eitaa"):
                self._require_admin()
                user_id = path.strip("/").split("/")[3]
                if not db.get_user(user_id):
                    raise AppError("User not found.")
                return self._json(_save_eitaa_token(user_id, body, enforce_caps=False))
            if path.startswith("/api/admin/users/") and path.endswith("/eitaa/channels"):
                self._require_admin()
                parts = path.strip("/").split("/")
                # api/admin/users/{id}/eitaa/channels
                if len(parts) != 6:
                    raise AppError("Not found.")
                user_id = parts[3]
                if not db.get_user(user_id):
                    raise AppError("User not found.")
                return self._json(_add_eitaa_channel(user_id, body, enforce_caps=False), 201)
            if path.startswith("/api/invoices/") and path.endswith("/paid"):
                user = self._require_user()
                invoice_id = path.split("/")[3]
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "multipart/form-data" in ctype:
                    fields, files = self._read_multipart()
                    file_item = files.get("receipt")
                    if not file_item:
                        raise AppError("فیش واریز را انتخاب کنید.")
                    filename, content, content_type = file_item
                    invoice = db.save_invoice_receipt(
                        invoice_id,
                        user["id"],
                        filename=filename,
                        content=content,
                        content_type=content_type,
                        payer_note=str(fields.get("payer_note") or ""),
                    )
                else:
                    # JSON without file only allowed if receipt already uploaded
                    invoice = db.mark_invoice_paid_by_user(
                        invoice_id, user["id"], str(body.get("payer_note") or "")
                    )
                return self._json({"invoice": invoice})
            if path.startswith("/api/invoices/") and path.endswith("/pay-bale"):
                user = self._require_user()
                invoice_id = path.split("/")[3]
                invoice = db.get_invoice(invoice_id)
                if not invoice or invoice["user_id"] != user["id"]:
                    raise AppError("فاکتور پیدا نشد.")
                from bale_payments import send_wallet_invoice

                result = send_wallet_invoice(user, invoice)
                return self._json(
                    {
                        "ok": True,
                        "invoice": db.get_invoice(invoice_id),
                        "bale": result,
                    }
                )
            if path.startswith("/api/admin/invoices/") and path.endswith("/confirm"):
                self._require_admin()
                invoice_id = path.split("/")[4]
                result = db.confirm_invoice(invoice_id)
                user = result.get("user")
                return self._json(
                    {
                        "invoice": result.get("invoice"),
                        "user": _admin_user(user) if user else None,
                    }
                )
            if path.startswith("/api/admin/invoices/") and path.endswith("/reject"):
                self._require_admin()
                invoice_id = path.split("/")[4]
                return self._json({"invoice": db.reject_invoice(invoice_id)})
            if path.startswith("/api/admin/users/") and path.endswith("/rotate-key"):
                self._require_admin()
                user_id = path.split("/")[4]
                return self._json({"user": _admin_user(db.rotate_api_key(user_id))})
            if path.startswith("/api/admin/users/") and path.endswith("/chat"):
                self._require_admin()
                parts = path.strip("/").split("/")
                # api/admin/users/{uid}/filters/{fid}/chat
                if len(parts) != 7 or parts[4] != "filters":
                    raise AppError("Not found.")
                user_id = parts[3]
                filter_id = parts[5]
                if not db.get_user(user_id):
                    raise AppError("User not found.")
                saved = db.set_filter_chat(user_id, filter_id, body.get("chat_id"))
                return self._json({"filter": filter_to_api(saved)})
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
            if path.endswith("/chat") and path.startswith("/api/filters/"):
                user = self._require_user()
                filter_id = path.split("/")[3]
                if "destinations" in body and isinstance(body.get("destinations"), list):
                    db.set_filter_destinations(user["id"], filter_id, body["destinations"])
                    saved = db.get_filter(filter_id, user["id"])
                else:
                    saved = db.set_filter_chat(user["id"], filter_id, body.get("chat_id"))
                return self._json({"filter": filter_to_api(saved)})
            if path.endswith("/destinations") and path.startswith("/api/filters/"):
                user = self._require_user()
                filter_id = path.split("/")[3]
                db.set_filter_destinations(user["id"], filter_id, body.get("destinations") or [])
                saved = db.get_filter(filter_id, user["id"])
                if not saved:
                    raise AppError("Filter not found.")
                return self._json({"filter": filter_to_api(saved)})
            if path.startswith("/api/admin/users/") and path.endswith("/destinations"):
                self._require_admin()
                parts = path.strip("/").split("/")
                # api/admin/users/{uid}/filters/{fid}/destinations
                if len(parts) != 7 or parts[4] != "filters":
                    raise AppError("Not found.")
                user_id = parts[3]
                filter_id = parts[5]
                if not db.get_user(user_id):
                    raise AppError("User not found.")
                db.set_filter_destinations(user_id, filter_id, body.get("destinations") or [])
                saved = db.get_filter(filter_id, user_id)
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
                        "bot_running": any(bot.running for bot in BOTS),
                        "bots": {bot.channel: bot.running for bot in BOTS},
                        "last_message": WATCHER.last_message,
                        "next_watch_at": WATCHER.next_run_at or None,
                    }
                )
            if path == "/api/admin/broadcast":
                self._require_admin()
                from messengers import admin_broadcast, bale_announcement_text, collect_broadcast_targets

                text = str(body.get("text") or "").strip()
                if body.get("preset") == "bale_announcement" and not text:
                    text = bale_announcement_text()
                scope = str(body.get("scope") or "private").strip().lower() or "private"
                channels = body.get("channels")
                if isinstance(channels, str):
                    channels = [c.strip() for c in channels.split(",") if c.strip()]
                if not isinstance(channels, list):
                    channels = None
                if body.get("dry_run"):
                    targets = collect_broadcast_targets(scope=scope, channels=channels)
                    return self._json(
                        {
                            "ok": True,
                            "dry_run": True,
                            "total": len(targets),
                            "targets": targets,
                            "text": text,
                        }
                    )
                return self._json(
                    admin_broadcast(text, scope=scope, channels=channels)
                )
            if path == "/api/tickets":
                user = self._require_user()
                ticket = db.create_ticket(
                    user["id"],
                    subject=str(body.get("subject") or ""),
                    body=str(body.get("body") or body.get("message") or ""),
                )
                return self._json({"ticket": ticket}, 201)
            if path.startswith("/api/tickets/") and path.endswith("/messages"):
                user = self._require_user()
                ticket_id = path.strip("/").split("/")[2]
                ticket = db.add_ticket_message(
                    ticket_id,
                    sender="user",
                    body=str(body.get("body") or body.get("message") or ""),
                    user_id=user["id"],
                )
                return self._json({"ticket": ticket})
            if path.startswith("/api/tickets/") and path.endswith("/close"):
                user = self._require_user()
                ticket_id = path.strip("/").split("/")[2]
                ticket = db.set_ticket_status(ticket_id, "closed", user_id=user["id"])
                return self._json({"ticket": ticket})
            if path.startswith("/api/admin/users/") and "/tickets/" in path and path.endswith("/messages"):
                self._require_admin()
                parts = path.strip("/").split("/")
                # api/admin/users/{uid}/tickets/{tid}/messages
                if len(parts) != 7:
                    raise AppError("Not found.")
                user_id = parts[3]
                ticket_id = parts[5]
                if not db.get_user(user_id):
                    raise AppError("User not found.")
                ticket = db.add_ticket_message(
                    ticket_id,
                    sender="admin",
                    body=str(body.get("body") or body.get("message") or ""),
                    user_id=user_id,
                )
                # Best-effort notify customer on linked messengers.
                try:
                    from messengers import build_messenger, collect_broadcast_targets

                    note = (
                        "پاسخ پشتیبانی دریافت شد.\n"
                        f"موضوع: {ticket.get('subject')}\n"
                        "برای مشاهده وارد پنل شوید:\n"
                        f"{public_base_url()}/app"
                    )
                    for dest in collect_broadcast_targets(scope="private", channels=None):
                        if dest["user_id"] != user_id:
                            continue
                        try:
                            build_messenger(dest["channel"]).send_text(note, chat_id=dest["chat_id"])
                        except Exception:
                            continue
                except Exception:
                    pass
                return self._json({"ticket": ticket})
            if path.startswith("/api/admin/users/") and path.endswith("/tickets"):
                self._require_admin()
                parts = path.strip("/").split("/")
                # api/admin/users/{uid}/tickets  -> create admin-initiated ticket
                if len(parts) != 5:
                    raise AppError("Not found.")
                user_id = parts[3]
                if not db.get_user(user_id):
                    raise AppError("User not found.")
                ticket = db.create_ticket_from_admin(
                    user_id,
                    subject=str(body.get("subject") or "پیام پشتیبانی"),
                    body=str(body.get("body") or body.get("message") or ""),
                )
                return self._json({"ticket": ticket}, 201)
            if path.startswith("/api/admin/users/") and path.endswith("/close"):
                self._require_admin()
                parts = path.strip("/").split("/")
                # api/admin/users/{uid}/tickets/{tid}/close
                if len(parts) != 7 or parts[4] != "tickets":
                    raise AppError("Not found.")
                user_id = parts[3]
                ticket_id = parts[5]
                ticket = db.set_ticket_status(ticket_id, "closed", user_id=user_id)
                return self._json({"ticket": ticket})
            if path == "/api/logout":
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"session=; Path=/; Max-Age=0; {self._cookie_flags()}")
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
                parts = path.strip("/").split("/")
                if len(parts) != 4:
                    raise AppError("Not found.")
                return self._json({"user": self._admin_update_user(parts[3], body)})
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
            if path == "/api/eitaa":
                user = self._require_user()
                db.clear_messenger_token(user["id"], "eitaa")
                return self._json({"ok": True, **_eitaa_payload(user["id"])})
            if path.startswith("/api/eitaa/channels/"):
                user = self._require_user()
                chat_id = path.rsplit("/", 1)[-1]
                db.delete_user_chat(user["id"], "eitaa", chat_id)
                return self._json({"ok": True, **_eitaa_payload(user["id"])})
            if path.startswith("/api/admin/users/") and "/eitaa/channels/" in path:
                self._require_admin()
                parts = path.strip("/").split("/")
                # api/admin/users/{id}/eitaa/channels/{chat}
                if len(parts) != 7:
                    raise AppError("Not found.")
                user_id = parts[3]
                chat_id = parts[6]
                if not db.get_user(user_id):
                    raise AppError("User not found.")
                db.delete_user_chat(user_id, "eitaa", chat_id)
                return self._json({"ok": True, **_eitaa_payload(user_id)})
            if path.startswith("/api/admin/users/") and path.endswith("/eitaa"):
                self._require_admin()
                parts = path.strip("/").split("/")
                if len(parts) != 5:
                    raise AppError("Not found.")
                user_id = parts[3]
                if not db.get_user(user_id):
                    raise AppError("User not found.")
                db.clear_messenger_token(user_id, "eitaa")
                return self._json({"ok": True, **_eitaa_payload(user_id)})
            if path.startswith("/api/admin/users/"):
                self._require_admin()
                user_id = path.rsplit("/", 1)[-1]
                if not user_id or user_id == "users":
                    raise AppError("User not found.")
                db.delete_user(user_id)
                return self._json({"ok": True})
            if path.startswith("/api/admin/plans/"):
                self._require_admin()
                plan_id = path.rsplit("/", 1)[-1]
                db.delete_plan(plan_id)
                return self._json({"ok": True})
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
        if "poll_interval_minutes" in body:
            fields["poll_interval_minutes"] = body.get("poll_interval_minutes")
        if "poll_offset_minutes" in body:
            fields["poll_offset_minutes"] = body.get("poll_offset_minutes")
        if "best_count" in body:
            fields["best_count"] = body.get("best_count")
        if "plan_id" in body:
            fields["plan_id"] = body.get("plan_id")
        if "max_filters" in body:
            fields["max_filters"] = body.get("max_filters")
        if "expires_at" in body:
            fields["expires_at"] = body.get("expires_at")
        if body.get("apply_plan"):
            return _admin_user(
                db.apply_subscription(
                    user_id,
                    str(body.get("plan_id") or "trial"),
                    renew=bool(body.get("renew", True)),
                    expires_at=body.get("expires_at") if "expires_at" in body else None,
                    apply_limits=bool(body.get("apply_limits", True)),
                )
            )
        user = db.update_user(user_id, **fields)
        return _admin_user(user)

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

    def _cookie_flags(self) -> str:
        flags = "HttpOnly; SameSite=Lax"
        if public_base_url().startswith("https://"):
            flags += "; Secure"
        return flags

    def _set_session_cookie(self, token: str) -> None:
        self.send_header(
            "Set-Cookie",
            f"session={token}; Path=/; Max-Age={30 * 24 * 3600}; {self._cookie_flags()}",
        )

    def _set_admin_cookie(self, token: str) -> None:
        self.send_header(
            "Set-Cookie",
            f"admin_session={token}; Path=/; Max-Age={14 * 24 * 3600}; {self._cookie_flags()}",
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

    def _read_multipart(self) -> tuple[dict[str, str], dict[str, tuple[str, bytes, str]]]:
        ctype = self.headers.get("Content-Type") or ""
        match = re.search(r"boundary=([^;]+)", ctype, flags=re.I)
        if not match:
            raise AppError("Invalid multipart request.")
        boundary = match.group(1).strip().strip('"')
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 7 * 1024 * 1024:
            raise AppError("حجم درخواست بیش از حد مجاز است.")
        raw = self.rfile.read(length)
        marker = b"--" + boundary.encode("utf-8")
        fields: dict[str, str] = {}
        files: dict[str, tuple[str, bytes, str]] = {}
        for part in raw.split(marker):
            if not part or part in (b"--\r\n", b"--"):
                continue
            if part.startswith(b"--"):
                continue
            if part.startswith(b"\r\n"):
                part = part[2:]
            if part.endswith(b"\r\n"):
                part = part[:-2]
            header_blob, sep, content = part.partition(b"\r\n\r\n")
            if not sep:
                continue
            headers = header_blob.decode("utf-8", errors="ignore")
            disp = ""
            part_ctype = "application/octet-stream"
            for line in headers.split("\r\n"):
                lower = line.lower()
                if lower.startswith("content-disposition:"):
                    disp = line
                elif lower.startswith("content-type:"):
                    part_ctype = line.split(":", 1)[1].strip()
            name_m = re.search(r'name="([^"]+)"', disp)
            if not name_m:
                continue
            name = name_m.group(1)
            file_m = re.search(r'filename="([^"]*)"', disp)
            if file_m is not None:
                filename = file_m.group(1) or "receipt"
                files[name] = (filename, content, part_ctype)
            else:
                fields[name] = content.decode("utf-8", errors="ignore")
        return fields, files

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


def _admin_user(user: dict) -> dict:
    from plans import user_capabilities

    config = load_config()
    interval = user_poll_interval_minutes(user, config)
    offset = user_poll_offset_minutes(user, config)
    return {
        **user,
        "poll_interval_minutes": user.get("poll_interval_minutes"),
        "poll_offset_minutes": int(user.get("poll_offset_minutes") or 0),
        "best_count": user.get("best_count"),
        "effective_poll_interval_minutes": interval,
        "effective_poll_offset_minutes": offset,
        "effective_best_count": user_best_count(user, config),
        "slot_preview": slot_preview_minutes(interval, offset),
        "default_poll_interval_minutes": poll_interval_minutes(config),
        "default_best_count": user_best_count(None, config),
        "filter_count": db.user_filter_count(user["id"]),
        "eitaa": _eitaa_payload(user["id"]),
        "capabilities": user_capabilities(user),
    }


def _safe_user(user: dict) -> dict:
    from plans import effective_max_criteria, user_capabilities

    return {
        "id": user["id"],
        "telegram_username": user.get("telegram_username") or "",
        "login_username": user.get("login_username") or "",
        "display_name": user["display_name"],
        "ai_enabled": user["ai_enabled"],
        "linked": user["linked"],
        "eitaa_configured": bool(user.get("eitaa_configured")),
        "public_slug": user.get("public_slug")
        or user.get("login_username")
        or user.get("telegram_username")
        or "",
        "telegram_chat_id": user.get("telegram_chat_id") or "",
        "has_password": bool(user.get("has_password")),
        "plan_id": user.get("plan_id") or "trial",
        "plan_name": user.get("plan_name") or "",
        "max_filters": user.get("max_filters"),
        "effective_max_filters": user.get("effective_max_filters"),
        "max_criteria": effective_max_criteria(user),
        "expires_at": user.get("expires_at") or "",
        "subscription_status": user.get("subscription_status") or {},
        "poll_interval_minutes": user.get("poll_interval_minutes"),
        "best_count": user.get("best_count"),
        "messenger_accounts": user.get("messenger_accounts") or [],
        "api_access": has_api_access(user),
        "capabilities": user_capabilities(user),
    }


def _eitaa_payload(user_id: str) -> dict:
    cred = db.get_messenger_credential(user_id, "eitaa")
    channels = db.list_user_chats(user_id, channel="eitaa")
    return {
        "configured": bool(cred and cred.get("configured")),
        "token_masked": (cred or {}).get("token_masked") or "",
        "updated_at": (cred or {}).get("updated_at") or "",
        "channels": channels,
        "instructions": [
            "در eitaayar.ir ثبت‌نام کنید و توکن API را از بخش API کپی کنید.",
            "ربات @sender را ادمین کانال/گروه ایتای خود کنید.",
            "کانال را در پنل ایتایار ثبت کنید و شناسه کانال (عددی یا username بدون @) را بردارید.",
            "توکن را همین‌جا ذخیره کنید، بعد شناسه کانال را اضافه کنید.",
            "در فیلتر، پیام‌رسان ایتا را انتخاب کنید و کانال را به‌عنوان مقصد بگذارید.",
        ],
        "normalize_hint": "مثال شناسه: mychannel یا 23333622",
    }


def _save_eitaa_token(user_id: str, body: dict, *, enforce_caps: bool = True) -> dict:
    from messengers import verify_eitaayar_token
    from plans import channel_allowed

    user = db.get_user(user_id)
    if enforce_caps and user and not channel_allowed(user, "eitaa"):
        raise AppError("پلن فعلی شما ایتا ندارد. پلن بالاتر بگیرید.")

    token = str(body.get("token") or "").strip()
    if not token:
        raise AppError("توکن ایتایار را وارد کنید.")
    info = verify_eitaayar_token(token)
    label = str(
        (info.get("username") if isinstance(info, dict) else "")
        or (info.get("first_name") if isinstance(info, dict) else "")
        or ""
    )
    db.set_messenger_token(user_id, "eitaa", token, label=label)
    return {"ok": True, "eitaa": _eitaa_payload(user_id), "account": info}


def _add_eitaa_channel(user_id: str, body: dict, *, enforce_caps: bool = True) -> dict:
    from messengers import normalize_eitaa_chat_id
    from plans import channel_allowed

    user = db.get_user(user_id)
    if enforce_caps and user and not channel_allowed(user, "eitaa"):
        raise AppError("پلن فعلی شما ایتا ندارد. پلن بالاتر بگیرید.")
    if not db.get_messenger_token(user_id, "eitaa"):
        raise AppError("اول توکن ایتایار را ذخیره کنید.")
    chat_id = normalize_eitaa_chat_id(str(body.get("chat_id") or body.get("id") or ""))
    if not chat_id:
        raise AppError("شناسه کانال ایتا را وارد کنید.")
    name = str(body.get("name") or chat_id).strip()[:80] or chat_id
    chat = db.upsert_user_chat(
        user_id,
        channel="eitaa",
        chat_id=chat_id,
        chat_type="channel",
        name=name,
        username=chat_id,
    )
    return {"ok": True, "chat": chat, "eitaa": _eitaa_payload(user_id)}


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
    if (os.getenv("BALE_BOT_TOKEN") or "").strip():
        BALE_BOT.start()
        print("Bale bot listening", flush=True)
    if any(bot.running for bot in BOTS):
        try:
            WATCHER.start()
            print("Watcher started automatically", flush=True)
        except Exception as exc:
            print(f"Watcher auto-start skipped: {exc}", flush=True)
    server = ReuseServer((host, port), Handler)
    print(f"Service: {public_base_url()}/", flush=True)
    print(f"Admin:   {public_base_url()}/admin", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        for bot in BOTS:
            bot.stop()
        WATCHER.stop()
        server.server_close()


if __name__ == "__main__":
    serve()
