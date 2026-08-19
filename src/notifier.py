from __future__ import annotations

import html
import time
from typing import Any

import requests

from divar import Listing

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

_bot_username_cache: dict[str, str | None] = {}


def telegram_bot_username(bot_token: str) -> str | None:
    if bot_token in _bot_username_cache:
        return _bot_username_cache[bot_token]
    try:
        response = requests.get(
            TELEGRAM_API.format(token=bot_token, method="getMe"),
            timeout=15,
        )
        data = response.json()
        username = (data.get("result") or {}).get("username") if data.get("ok") else None
    except requests.RequestException:
        username = None
    _bot_username_cache[bot_token] = username
    return username


def chat_record(chat: dict[str, Any] | None) -> dict[str, Any] | None:
    if not chat or "id" not in chat:
        return None
    return {
        "id": str(chat["id"]),
        "type": str(chat.get("type") or ""),
        "name": str(chat.get("first_name") or chat.get("title") or "").strip(),
        "username": str(chat.get("username") or ""),
    }


def chat_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("message", "edited_message", "channel_post", "my_chat_member"):
        payload = update.get(key) or {}
        record = chat_record(payload.get("chat"))
        if record:
            return record
    return None


def list_recent_chats(bot_token: str) -> list[dict[str, Any]]:
    response = requests.get(
        TELEGRAM_API.format(token=bot_token, method="getUpdates"),
        timeout=20,
        params={"timeout": 0, "allowed_updates": '["message","edited_message","channel_post","my_chat_member"]'},
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or "telegram error")
    chats: dict[str, dict[str, Any]] = {}
    for item in data.get("result") or []:
        record = chat_from_update(item)
        if record:
            chats[record["id"]] = record
    return list(chats.values())


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
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

    def send_listing(
        self,
        listing: Listing,
        rank: int | None = None,
        reason: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        caption = format_listing(listing, rank=rank, reason=reason)
        target = str(chat_id or self.chat_id)
        if self.send_photos and listing.image_url:
            try:
                self._call(
                    "sendPhoto",
                    {
                        "chat_id": target,
                        "photo": listing.image_url,
                        "caption": caption[:1024],
                        "parse_mode": "HTML",
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
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
        )

    def send_text(
        self,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        chat_id: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": str(chat_id or self.chat_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self._call("sendMessage", payload)

    def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict[str, Any]]:
        url = TELEGRAM_API.format(token=self.bot_token, method="getUpdates")
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
            raise RuntimeError(data.get("description") or "telegram error")
        return list(data.get("result") or [])

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = TELEGRAM_API.format(token=self.bot_token, method=method)
        response = self.session.post(url, json=payload, timeout=self.timeout)
        if response.status_code == 429:
            retry_after = int((response.json().get("parameters") or {}).get("retry_after") or 3)
            time.sleep(retry_after + 1)
            response = self.session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or "telegram error")
        time.sleep(self.delay_seconds)
        return data


def format_listing(listing: Listing, rank: int | None = None, reason: str | None = None) -> str:
    title = html.escape(listing.title)
    if rank is not None:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        prefix = medals.get(rank, f"{rank}.")
        lines = [f"{prefix} <b>{title}</b>"]
    else:
        lines = [f"🚗 <b>{title}</b>"]
    lines.append(f"🔎 {html.escape(listing.filter_name)}")
    if listing.price:
        lines.append(f"💰 {html.escape(listing.price)}")
    if listing.mileage:
        lines.append(f"🛣️ {html.escape(listing.mileage)}")
    if listing.location:
        lines.append(f"📍 {html.escape(listing.location)}")
    if reason:
        lines.append(f"🧠 {html.escape(reason)}")
    lines.append(f'🔗 <a href="{html.escape(listing.url, quote=True)}">مشاهده در دیوار</a>')
    return "\n".join(lines)
