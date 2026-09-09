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
}

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
                "allowed_updates": '["message","edited_message","channel_post","my_chat_member"]',
            },
            timeout=timeout + 10,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or f"{self.channel} error")
        return list(data.get("result") or [])


class BaleBotClient(TelegramBotClient):
    """Bale uses a Telegram-compatible Bot API."""

    channel = "bale"
    api_template = BALE_API
    deep_link_base = "https://ble.ir/{username}"


def messenger_env_token(channel: str) -> str:
    ch = str(channel or "").strip().lower()
    if ch == "telegram":
        return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if ch == "bale":
        return os.getenv("BALE_BOT_TOKEN", "").strip()
    return os.getenv(f"{ch.upper()}_BOT_TOKEN", "").strip()


def messenger_configs(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Active messenger channels based on env tokens (gradual rollout)."""
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
                "client_cls": cls,
                "token": token,
                "send_photos": send_photos,
                "delay_seconds": delay,
            }
        )
    return out


def build_messenger(channel: str, config: dict[str, Any] | None = None) -> MessengerClient:
    load_dotenv()
    config = config or load_config()
    ch = str(channel or "telegram").strip().lower() or "telegram"
    token = messenger_env_token(ch)
    if not token:
        raise AppError(f"توکن ربات {CHANNEL_LABELS.get(ch, ch)} تنظیم نشده است.")
    telegram_cfg = config.get("telegram") or {}
    kwargs = {
        "bot_token": token,
        "chat_id": "0",
        "send_photos": bool(telegram_cfg.get("send_photos", True)),
        "delay_seconds": float(telegram_cfg.get("delay_seconds", 0.8)),
    }
    if ch == "telegram":
        return TelegramBotClient(**kwargs)
    if ch == "bale":
        return BaleBotClient(**kwargs)
    raise AppError(f"پیام‌رسان ناشناخته: {ch}")


def public_messenger_payload(user: dict[str, Any] | None = None) -> list[dict[str, Any]]:
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
                "linked": bool(acc and acc.get("account_id")),
                "account_id": (acc or {}).get("account_id") or "",
                "username": (acc or {}).get("username") or "",
            }
        )
    return payload


# Aliases matching plan naming
TelegramMessenger = TelegramBotClient
BaleMessenger = BaleBotClient
