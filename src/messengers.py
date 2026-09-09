from __future__ import annotations

import os
import time
from typing import Any, Protocol

import requests

from config_store import AppError, load_config, load_dotenv
from divar import Listing
from notifier import TelegramNotifier, telegram_bot_username

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
BALE_API = "https://tapi.bale.ai/bot{token}/{method}"

CHANNEL_LABELS = {
    "telegram": "تلگرام",
    "bale": "بله",
    "eitaa": "ایتا",
}

EITAAYAR_API = "https://eitaayar.ir/api/{token}/{method}"

_bot_username_cache: dict[str, str | None] = {}


class MessengerClient(Protocol):
    channel: str

    def send_text(
        self,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        chat_id: str | None = None,
    ) -> None: ...

    def send_listing(
        self,
        listing: Listing,
        rank: int | None = None,
        reason: str | None = None,
        chat_id: str | None = None,
    ) -> None: ...

    def bot_deep_link(self, payload: str = "link") -> str: ...

    def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict[str, Any]]: ...


def _bot_username(api_template: str, bot_token: str) -> str | None:
    cache_key = f"{api_template}:{bot_token}"
    if cache_key in _bot_username_cache and _bot_username_cache[cache_key]:
        return _bot_username_cache[cache_key]
    try:
        response = requests.get(
            api_template.format(token=bot_token, method="getMe"),
            timeout=15,
        )
        data = response.json()
        username = (data.get("result") or {}).get("username") if data.get("ok") else None
    except (requests.RequestException, ValueError, TypeError):
        username = None
    if username:
        _bot_username_cache[cache_key] = username
    return username


class TelegramBotClient(TelegramNotifier):
    """Telegram adaptor implementing the shared messenger surface."""

    channel = "telegram"
    api_template = TELEGRAM_API
    deep_link_base = "https://t.me/{username}"

    def __init__(
        self,
        bot_token: str,
        chat_id: str = "0",
        send_photos: bool = True,
        delay_seconds: float = 0.8,
        timeout: int = 30,
    ) -> None:
        super().__init__(
            bot_token=bot_token,
            chat_id=chat_id,
            send_photos=send_photos,
            delay_seconds=delay_seconds,
            timeout=timeout,
        )

    def bot_username(self) -> str | None:
        if self.api_template == TELEGRAM_API:
            return telegram_bot_username(self.bot_token)
        return _bot_username(self.api_template, self.bot_token)

    def bot_deep_link(self, payload: str = "link") -> str:
        username = self.bot_username()
        if not username:
            return ""
        base = self.deep_link_base.format(username=username)
        start = str(payload or "link").strip() or "link"
        return f"{base}?start={start}"

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.api_template.format(token=self.bot_token, method=method)
        response = self.session.post(url, json=payload, timeout=self.timeout)
        if response.status_code == 429:
            retry_after = int((response.json().get("parameters") or {}).get("retry_after") or 3)
            time.sleep(retry_after + 1)
            response = self.session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or f"{self.channel} error")
        time.sleep(self.delay_seconds)
        return data

    def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict[str, Any]]:
        url = self.api_template.format(token=self.bot_token, method="getUpdates")
        response = self.session.get(
            url,
            params={
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": (
                    '["message","edited_message","channel_post","my_chat_member","pre_checkout_query"]'
                ),
            },
            timeout=timeout + 10,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or f"{self.channel} error")
        return list(data.get("result") or [])


class BaleBotClient(TelegramBotClient):
    """Bale Bot API is Telegram-like, but text is always Markdown (not HTML)."""

    channel = "bale"
    api_template = BALE_API
    deep_link_base = "https://ble.ir/{username}"

    def send_invoice(
        self,
        *,
        chat_id: str,
        title: str,
        description: str,
        payload: str,
        provider_token: str,
        prices: list[dict[str, Any]],
        photo_url: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "chat_id": str(chat_id),
            "title": str(title)[:32],
            "description": str(description)[:255],
            "payload": str(payload)[:128],
            "provider_token": str(provider_token),
            "prices": prices,
        }
        if photo_url:
            body["photo_url"] = photo_url
        return self._call("sendInvoice", body)

    def answer_pre_checkout_query(
        self,
        pre_checkout_query_id: str,
        *,
        ok: bool,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "pre_checkout_query_id": str(pre_checkout_query_id),
            "ok": bool(ok),
        }
        if not ok and error_message:
            body["error_message"] = str(error_message)[:200]
        return self._call("answerPreCheckoutQuery", body)

    def inquire_transaction(self, transaction_id: str) -> dict[str, Any]:
        return self._call("inquireTransaction", {"transaction_id": str(transaction_id)})

    def send_listing(
        self,
        listing: Listing,
        rank: int | None = None,
        reason: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        from notifier import format_listing_bale

        caption = format_listing_bale(listing, rank=rank, reason=reason)
        target = str(chat_id or self.chat_id)
        if self.send_photos and listing.image_url:
            try:
                self._call(
                    "sendPhoto",
                    {
                        "chat_id": target,
                        "photo": listing.image_url,
                        "caption": caption[:1024],
                    },
                )
                return
            except requests.HTTPError:
                pass
        self._call(
            "sendMessage",
            {
                "chat_id": target,
                "text": caption,
            },
        )

    def send_text(
        self,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        chat_id: str | None = None,
    ) -> None:
        import re

        # Drop Telegram HTML tags; keep inner text. Bare URLs remain clickable.
        cleaned = re.sub(r"<br\s*/?>", "\n", str(text or ""), flags=re.I)
        cleaned = re.sub(r"</?a\b[^>]*>", "", cleaned, flags=re.I)
        cleaned = re.sub(r"</?[^>]+>", "", cleaned)
        payload: dict[str, Any] = {
            "chat_id": str(chat_id or self.chat_id),
            "text": cleaned,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self._call("sendMessage", payload)


def normalize_eitaa_chat_id(value: str) -> str:
    raw = str(value or "").strip()
    for prefix in (
        "https://eitaa.com/",
        "http://eitaa.com/",
        "https://www.eitaa.com/",
        "http://www.eitaa.com/",
        "eitaa.com/",
    ):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix) :]
            break
    return raw.strip().lstrip("@").strip().strip("/")


class EitaaBotClient:
    """Eitaayar one-way channel/group sender (no interactive bot API yet)."""

    channel = "eitaa"
    link_mode = "channel_only"

    def __init__(
        self,
        bot_token: str,
        chat_id: str = "0",
        send_photos: bool = True,
        delay_seconds: float = 0.8,
        timeout: int = 30,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.send_photos = send_photos
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.session = requests.Session()

    def bot_username(self) -> str | None:
        return None

    def bot_deep_link(self, payload: str = "link") -> str:
        return ""

    def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict[str, Any]]:
        return []

    def _call_form(self, method: str, data: dict[str, Any], files: dict | None = None) -> dict[str, Any]:
        url = EITAAYAR_API.format(token=self.bot_token, method=method)
        response = self.session.post(url, data=data, files=files, timeout=self.timeout)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("پاسخ نامعتبر ایتایار") from exc
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise RuntimeError(payload.get("description") or "خطای ایتایار")
        time.sleep(self.delay_seconds)
        return payload if isinstance(payload, dict) else {"ok": True, "result": payload}

    def send_text(
        self,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        chat_id: str | None = None,
    ) -> None:
        import re

        cleaned = re.sub(r"<br\s*/?>", "\n", str(text or ""), flags=re.I)
        cleaned = re.sub(r"</?a\b[^>]*>", "", cleaned, flags=re.I)
        cleaned = re.sub(r"</?[^>]+>", "", cleaned)
        target = normalize_eitaa_chat_id(str(chat_id or self.chat_id))
        if not target:
            raise RuntimeError("شناسه کانال ایتا خالی است.")
        self._call_form(
            "sendmessage",
            {
                "chat_id": target,
                "text": cleaned,
            },
        )

    def send_listing(
        self,
        listing: Listing,
        rank: int | None = None,
        reason: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        from notifier import format_listing_plain
        import tempfile
        from pathlib import Path

        caption = format_listing_plain(listing, rank=rank, reason=reason)
        target = normalize_eitaa_chat_id(str(chat_id or self.chat_id))
        if not target:
            raise RuntimeError("شناسه کانال ایتا خالی است.")
        if self.send_photos and listing.image_url:
            tmp_path: Path | None = None
            try:
                img = self.session.get(str(listing.image_url), timeout=20)
                img.raise_for_status()
                suffix = ".jpg"
                ctype = (img.headers.get("Content-Type") or "").lower()
                if "png" in ctype:
                    suffix = ".png"
                elif "webp" in ctype:
                    suffix = ".webp"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(img.content)
                    tmp_path = Path(tmp.name)
                with tmp_path.open("rb") as fh:
                    self._call_form(
                        "sendfile",
                        {"chat_id": target, "caption": caption[:1024]},
                        files={"file": (tmp_path.name, fh)},
                    )
                return
            except Exception:
                pass
            finally:
                if tmp_path is not None:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        self.send_text(caption, chat_id=target)


def messenger_env_token(channel: str) -> str:
    ch = str(channel or "").strip().lower()
    if ch == "telegram":
        return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if ch == "bale":
        return os.getenv("BALE_BOT_TOKEN", "").strip()
    if ch == "eitaa":
        # Legacy/global fallback only; preferred path is per-user token in DB.
        return (
            os.getenv("EITAAYAR_TOKEN", "").strip()
            or os.getenv("EITAYAR_TOKEN", "").strip()
            or os.getenv("EITAA_BOT_TOKEN", "").strip()
        )
    return os.getenv(f"{ch.upper()}_BOT_TOKEN", "").strip()


def verify_eitaayar_token(token: str) -> dict[str, Any]:
    value = str(token or "").strip()
    if not value:
        raise AppError("توکن ایتایار خالی است.")
    url = EITAAYAR_API.format(token=value, method="getMe")
    try:
        response = requests.post(url, timeout=20)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AppError("ارتباط با ایتایار برقرار نشد.") from exc
    if not isinstance(data, dict) or not data.get("ok"):
        raise AppError(
            (data.get("description") if isinstance(data, dict) else None)
            or "توکن ایتایار نامعتبر است."
        )
    return data.get("result") or {}


def messenger_configs(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Active interactive messenger channels based on env tokens."""
    load_dotenv()
    config = config or load_config()
    telegram_cfg = config.get("telegram") or {}
    send_photos = bool(telegram_cfg.get("send_photos", True))
    delay = float(telegram_cfg.get("delay_seconds", 0.8))
    out: list[dict[str, Any]] = []
    for channel, cls, deep_hint in (
        ("telegram", TelegramBotClient, "t.me"),
        ("bale", BaleBotClient, "ble.ir"),
    ):
        token = messenger_env_token(channel)
        if not token:
            continue
        client = cls(bot_token=token, chat_id="0", send_photos=send_photos, delay_seconds=delay)
        username = client.bot_username()
        out.append(
            {
                "channel": channel,
                "label": CHANNEL_LABELS.get(channel, channel),
                "enabled": True,
                "bot_username": username,
                "deep_link": client.bot_deep_link("link") if username else "",
                "deep_hint": deep_hint,
                "link_mode": "bot",
                "client_cls": cls,
                "token": token,
                "send_photos": send_photos,
                "delay_seconds": delay,
            }
        )
    return out


def build_messenger(
    channel: str,
    config: dict[str, Any] | None = None,
    *,
    token: str | None = None,
) -> MessengerClient:
    load_dotenv()
    config = config or load_config()
    ch = str(channel or "telegram").strip().lower() or "telegram"
    telegram_cfg = config.get("telegram") or {}
    kwargs = {
        "bot_token": "",
        "chat_id": "0",
        "send_photos": bool(telegram_cfg.get("send_photos", True)),
        "delay_seconds": float(telegram_cfg.get("delay_seconds", 0.8)),
    }
    if ch == "eitaa":
        tok = str(token or "").strip() or messenger_env_token("eitaa")
        if not tok:
            raise AppError("توکن ایتایار تنظیم نشده است.")
        kwargs["bot_token"] = tok
        return EitaaBotClient(**kwargs)
    tok = str(token or "").strip() or messenger_env_token(ch)
    if not tok:
        raise AppError(f"توکن ربات {CHANNEL_LABELS.get(ch, ch)} تنظیم نشده است.")
    kwargs["bot_token"] = tok
    if ch == "telegram":
        return TelegramBotClient(**kwargs)
    if ch == "bale":
        return BaleBotClient(**kwargs)
    raise AppError(f"پیام‌رسان ناشناخته: {ch}")


def messenger_client_for_user(
    user: dict[str, Any],
    channel: str,
    config: dict[str, Any] | None = None,
) -> MessengerClient:
    import db

    ch = str(channel or "").strip().lower() or "telegram"
    if ch == "eitaa":
        tok = db.get_messenger_token(user["id"], "eitaa")
        if not tok:
            raise AppError("توکن ایتایار این حساب تنظیم نشده است.")
        return build_messenger("eitaa", config, token=tok)
    return build_messenger(ch, config)


def public_messenger_payload(user: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    import db

    accounts = {
        str(a.get("channel") or "").lower(): a
        for a in (user or {}).get("messenger_accounts") or []
    }
    # Legacy telegram link
    if user and user.get("telegram_chat_id") and "telegram" not in accounts:
        accounts["telegram"] = {
            "channel": "telegram",
            "account_id": user.get("telegram_chat_id"),
            "username": user.get("telegram_username") or "",
        }
    eitaa_chats = []
    eitaa_cred = None
    if user:
        eitaa_chats = [
            c for c in db.list_user_chats(user["id"], channel="eitaa") if c.get("id")
        ]
        eitaa_cred = db.get_messenger_credential(user["id"], "eitaa")
    payload = []
    for item in messenger_configs():
        acc = accounts.get(item["channel"])
        payload.append(
            {
                "channel": item["channel"],
                "label": item["label"],
                "enabled": True,
                "bot_username": item["bot_username"],
                "deep_link": item["deep_link"],
                "link_mode": item.get("link_mode") or "bot",
                "linked": bool(acc and acc.get("account_id")),
                "configured": True,
                "account_id": (acc or {}).get("account_id") or "",
                "username": (acc or {}).get("username") or "",
                "hint": "",
            }
        )
    # Eitaa is always offered; token is per-customer (Eitaayar).
    payload.append(
        {
            "channel": "eitaa",
            "label": CHANNEL_LABELS["eitaa"],
            "enabled": True,
            "bot_username": None,
            "deep_link": "",
            "link_mode": "channel_only",
            "linked": bool(eitaa_cred and eitaa_chats),
            "configured": bool(eitaa_cred and eitaa_cred.get("configured")),
            "account_id": "",
            "username": "",
            "token_masked": (eitaa_cred or {}).get("token_masked") or "",
            "channels": eitaa_chats,
            "hint": (
                "توکن ایتایار خود را در بخش ایتا ذخیره کنید، @sender را ادمین کانال کنید "
                "و شناسه کانال را اضافه کنید."
            ),
        }
    )
    return payload


# Aliases matching plan naming
TelegramMessenger = TelegramBotClient
BaleMessenger = BaleBotClient
EitaaMessenger = EitaaBotClient


def collect_broadcast_targets(
    *,
    scope: str = "private",
    channels: list[str] | None = None,
    active_only: bool = True,
) -> list[dict[str, str]]:
    """Collect chat destinations for admin broadcast.

    scope:
      - private: linked messenger accounts (+ legacy telegram_chat_id)
      - all: every discovered user chat (private/group/channel)
    """
    import db

    wanted = {str(c).strip().lower() for c in (channels or []) if str(c).strip()}
    scope_key = str(scope or "private").strip().lower()
    if scope_key not in {"private", "all"}:
        raise AppError("scope باید private یا all باشد.")
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(channel: str, chat_id: str, *, user_id: str, label: str = "") -> None:
        ch = str(channel or "").strip().lower() or "telegram"
        cid = str(chat_id or "").strip()
        if not cid:
            return
        if wanted and ch not in wanted:
            return
        key = (ch, cid)
        if key in seen:
            return
        seen.add(key)
        out.append(
            {
                "channel": ch,
                "chat_id": cid,
                "user_id": user_id,
                "label": label,
            }
        )

    for user in db.list_users():
        if active_only and not user.get("active"):
            continue
        uid = str(user["id"])
        if scope_key == "private":
            for acc in user.get("messenger_accounts") or []:
                add(
                    str(acc.get("channel") or "telegram"),
                    str(acc.get("account_id") or ""),
                    user_id=uid,
                    label=str(acc.get("display_name") or acc.get("username") or "خصوصی"),
                )
            tg = str(user.get("telegram_chat_id") or "").strip()
            if tg:
                add("telegram", tg, user_id=uid, label="تلگرام خصوصی")
        else:
            for chat in db.list_user_chats(uid):
                add(
                    str(chat.get("channel") or "telegram"),
                    str(chat.get("id") or ""),
                    user_id=uid,
                    label=str(chat.get("name") or chat.get("username") or chat.get("type") or ""),
                )
    return out


def admin_broadcast(
    text: str,
    *,
    scope: str = "private",
    channels: list[str] | None = None,
    active_only: bool = True,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = str(text or "").strip()
    if not message:
        raise AppError("متن پیام خالی است.")
    if len(message) > 3500:
        raise AppError("متن پیام خیلی طولانی است (حداکثر حدود ۳۵۰۰ کاراکتر).")
    targets = collect_broadcast_targets(scope=scope, channels=channels, active_only=active_only)
    if not targets:
        raise AppError("هیچ مقصدی برای ارسال پیدا نشد.")
    config = config or load_config()
    clients: dict[str, MessengerClient] = {}
    sent = 0
    failed = 0
    details: list[dict[str, Any]] = []
    for dest in targets:
        channel = dest["channel"]
        chat_id = dest["chat_id"]
        try:
            if channel not in clients:
                clients[channel] = build_messenger(channel, config)
            clients[channel].send_text(message, chat_id=chat_id)
            sent += 1
            details.append({**dest, "status": "ok"})
        except Exception as exc:
            failed += 1
            details.append({**dest, "status": "error", "error": str(exc)})
    return {
        "ok": True,
        "sent": sent,
        "failed": failed,
        "total": len(targets),
        "scope": scope,
        "channels": sorted({d["channel"] for d in targets}),
        "details": details,
        "message": f"ارسال گروهی: {sent} موفق · {failed} ناموفق از {len(targets)} مقصد",
    }


def bale_announcement_text() -> str:
    """Default announcement when Bale bot is enabled."""
    link = ""
    username = ""
    for item in messenger_configs():
        if item["channel"] == "bale":
            link = item.get("deep_link") or ""
            username = item.get("bot_username") or ""
            break
    if not link and username:
        link = f"https://ble.ir/{username}?start=link"
    if not link:
        link = "https://ble.ir/divar_watcher_bot?start=link"
    return (
        "ربات بله هم اضافه شد ✅\n\n"
        "از این به بعد می‌توانید آگهی‌های دیوار را علاوه بر تلگرام، در بله هم دریافت کنید.\n\n"
        f"لینک اتصال بازوی بله:\n{link}\n\n"
        "طریقه استفاده:\n"
        "۱) وارد پنل وب شوید\n"
        "۲) در بخش «پیام‌رسان‌ها» روی بله بزنید و بازو را استارت/لاگین کنید "
        "(همان یوزرنیم و رمز پنل)\n"
        "۳) فیلتر را ویرایش کنید → پیام‌رسان بله را انتخاب کنید → چت را اضافه کنید → ذخیره\n\n"
        "یک فیلتر می‌تواند همزمان به چند چت در تلگرام و بله پیام بفرستد.\n"
        "اگر سوالی بود از پشتیبانی بپرسید."
    )
