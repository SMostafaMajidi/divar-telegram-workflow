from __future__ import annotations

import os
from typing import Any

import requests

from ai_rank import pick_best_ai
from config_store import (
    DATA_DIR,
    AppError,
    filter_from_api,
    filter_to_api,
    load_config,
    load_dotenv,
    user_best_count,
    user_poll_interval_minutes,
)
from divar import DivarClient, Listing
from notifier import TelegramNotifier
import db

_client: DivarClient | None = None


def get_client() -> DivarClient:
    global _client
    if _client is None:
        _client = DivarClient(DATA_DIR)
    return _client


def build_notifier(config: dict[str, Any] | None = None, *, require_chat: bool = False) -> TelegramNotifier:
    load_dotenv()
    config = config or load_config()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise AppError("TELEGRAM_BOT_TOKEN is missing.")
    telegram = config.get("telegram") or {}
    return TelegramNotifier(
        bot_token=token,
        chat_id="0",
        send_photos=bool(telegram.get("send_photos", True)),
        delay_seconds=float(telegram.get("delay_seconds", 0.8)),
    )


def destination_chat_id(user: dict[str, Any], spec: dict[str, Any] | None = None) -> str:
    if spec and str(spec.get("chat_id") or "").strip():
        return str(spec["chat_id"]).strip()
    return str(user.get("telegram_chat_id") or "").strip()


def collect_listings(specs: list[dict[str, Any]]) -> list[Listing]:
    client = get_client()
    listings: list[Listing] = []
    seen: set[str] = set()
    try:
        for spec in specs:
            found = client.search_filter(spec)
            for item in found:
                if item.token in seen:
                    continue
                seen.add(item.token)
                listings.append(item)
    except requests.RequestException as exc:
        raise AppError("Divar did not respond. Try again in a moment.") from exc
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    return listings


def preview_spec(body: dict[str, Any], limit: int = 24) -> dict[str, Any]:
    spec = filter_from_api(body)
    spec = dict(spec)
    spec["max_pages"] = max(1, min(int(spec.get("max_pages") or 2), 3))
    try:
        listings = get_client().search_filter(spec)[:limit]
    except requests.RequestException as exc:
        raise AppError("Divar did not respond. Try again in a moment.") from exc
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    return {
        "count": len(listings),
        "filter": spec.get("name"),
        "listings": [item.to_dict() for item in listings],
    }


def best_count(config: dict[str, Any] | None = None, user: dict[str, Any] | None = None) -> int:
    return user_best_count(user, config)


def send_best_for_user(user: dict[str, Any], count: int | None = None) -> dict[str, Any]:
    if not user.get("ai_enabled"):
        raise AppError("رتبه‌بندی هوشمند برای این حساب فعال نیست. از پشتیبانی درخواست کنید.")
    specs = db.list_filters(user["id"], enabled_only=True)
    if not specs:
        raise AppError("No enabled filters to run.")
    config = load_config()
    listings = collect_listings(specs)
    wanted = count if count is not None else best_count(config, user)
    chosen, source = pick_best_ai(listings, wanted)
    notifier = build_notifier(config)
    chat_id = destination_chat_id(user)
    if not chat_id:
        raise AppError("Telegram chat is not linked yet.")
    if not chosen:
        notifier.send_text("آگهی مناسبی با فیلترهای فعال پیدا نشد.", chat_id=chat_id)
        return {"sent": 0, "found": 0, "listings": [], "message": "No matching listings."}
    by_id = {str(spec.get("id")): spec for spec in specs}
    label = "با مدل زبانی" if source == "ai" else "با رتبه‌بندی ساده"
    notifier.send_text(
        f"{len(chosen)} آگهی برتر از {len(listings)} آگهی فعال ({label}):",
        chat_id=chat_id,
    )
    for index, (item, reason) in enumerate(chosen, start=1):
        target = destination_chat_id(user, by_id.get(item.filter_id))
        notifier.send_listing(item, rank=index, reason=reason, chat_id=target)
        db.cache_listing(user["id"], item.filter_id, item.to_dict())
    return {
        "sent": len(chosen),
        "found": len(listings),
        "source": source,
        "listings": [item.to_dict() for item, _reason in chosen],
        "message": f"Sent top {len(chosen)} of {len(listings)} listings ({source}).",
        "filters": [spec.get("name") for spec in specs],
    }


def watch_tick(user_ids: list[str] | None = None) -> dict[str, Any]:
    from messengers import build_messenger

    config = load_config()
    bundles = db.active_users_with_filters()
    if user_ids is not None:
        wanted = set(user_ids)
        bundles = [bundle for bundle in bundles if bundle["user"]["id"] in wanted]
    if not bundles:
        return {
            "sent": 0,
            "found": 0,
            "new": 0,
            "message": "No active linked users with filters.",
            "users": 0,
        }
    clients: dict[str, Any] = {}
    sent = 0
    found = 0
    newest_count = 0
    for bundle in bundles:
        user = bundle["user"]
        max_age = user_poll_interval_minutes(user, config)
        for spec in bundle["filters"]:
            filter_id = str(spec.get("id") or "")
            filter_name = str(spec.get("name") or filter_id)
            try:
                listings = collect_listings([spec])
            except Exception as exc:
                db.log_watch_event(
                    user["id"],
                    action="scan",
                    status="failure",
                    filter_id=filter_id,
                    filter_name=filter_name,
                    platform="divar",
                    channel="telegram",
                    message=f"جستجو ناموفق: {exc}",
                    detail={"error": str(exc)},
                )
                continue

            found += len(listings)
            newest = [
                item
                for item in listings
                if item.age_minutes is not None and item.age_minutes <= max_age
            ]
            newest_count += len(newest)
            destinations = db.resolve_filter_destinations(user, spec)
            fresh = [
                item
                for item in newest
                if not db.is_seen(user["id"], filter_id, item.token)
            ]

            if not destinations:
                db.log_watch_event(
                    user["id"],
                    action="scan",
                    status="skipped",
                    filter_id=filter_id,
                    filter_name=filter_name,
                    platform="divar",
                    channel="telegram",
                    found_count=len(listings),
                    new_count=len(fresh),
                    message="هیچ مقصد ارسالی تنظیم نشده؛ ارسال رد شد.",
                )
                continue

            db.log_watch_event(
                user["id"],
                action="scan",
                status="success",
                filter_id=filter_id,
                filter_name=filter_name,
                platform="divar",
                channel=destinations[0]["channel"],
                found_count=len(listings),
                new_count=len(fresh),
                destination=",".join(f"{d['channel']}:{d['chat_id']}" for d in destinations),
                message=(
                    f"جستجو: {len(listings)} آگهی · تازه: {len(fresh)} · مقصدها: {len(destinations)}"
                    if fresh
                    else f"جستجو: {len(listings)} آگهی · آگهی تازه نبود"
                ),
            )

            if not fresh:
                continue

            any_delivered = False
            for dest in destinations:
                channel = dest["channel"]
                chat_id = dest["chat_id"]
                try:
                    if channel not in clients:
                        clients[channel] = build_messenger(channel, config)
                    client = clients[channel]
                except Exception as exc:
                    db.log_watch_event(
                        user["id"],
                        action="deliver",
                        status="failure",
                        filter_id=filter_id,
                        filter_name=filter_name,
                        platform="divar",
                        channel=channel,
                        found_count=len(listings),
                        new_count=len(fresh),
                        destination=chat_id,
                        message=f"پیام‌رسان در دسترس نیست: {exc}",
                        detail={"error": str(exc)},
                    )
                    continue

                delivered = 0
                failed = 0
                last_error = ""
                for item in fresh:
                    try:
                        client.send_listing(item, chat_id=chat_id)
                        db.cache_listing(user["id"], filter_id, item.to_dict())
                        delivered += 1
                        any_delivered = True
                    except Exception as exc:
                        failed += 1
                        last_error = str(exc)
                sent += delivered
                if failed and not delivered:
                    status = "failure"
                    message = f"ارسال ناموفق ({failed}): {last_error}"
                elif failed:
                    status = "partial"
                    message = f"ارسال جزئی: {delivered} موفق · {failed} ناموفق"
                else:
                    status = "success"
                    message = f"ارسال موفق: {delivered} آگهی"
                db.log_watch_event(
                    user["id"],
                    action="deliver",
                    status=status,
                    filter_id=filter_id,
                    filter_name=filter_name,
                    platform="divar",
                    channel=channel,
                    found_count=len(listings),
                    new_count=len(fresh),
                    sent_count=delivered,
                    destination=chat_id,
                    message=message,
                    detail={"failed": failed, "error": last_error} if failed else {},
                )

            if any_delivered or fresh:
                # Mark seen once after attempting all destinations to avoid re-spam.
                db.mark_seen(user["id"], filter_id, [item.token for item in fresh])
    return {
        "sent": sent,
        "found": found,
        "new": newest_count,
        "users": len(bundles),
        "message": (
            f"Sent {sent} listings."
            if sent
            else f"No new listings for {len(bundles)} due user(s)."
        ),
    }


def save_user_filter(user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    existing = None
    incoming_id = str(body.get("id") or "").strip()
    if incoming_id:
        existing = db.get_filter(incoming_id, user_id)
    spec = filter_from_api(body, existing)
    saved = db.upsert_filter(user_id, spec)
    return filter_to_api(saved)
