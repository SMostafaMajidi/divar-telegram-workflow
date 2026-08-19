from __future__ import annotations

import os
from typing import Any

import requests

from config_store import (
    DATA_DIR,
    AppError,
    filter_from_api,
    get_filter,
    load_config,
    load_dotenv,
    poll_interval_seconds,
)
from ai_rank import pick_best_ai
from divar import DivarClient, Listing
from notifier import TelegramNotifier
from store import SeenStore

_client: DivarClient | None = None


def get_client() -> DivarClient:
    global _client
    if _client is None:
        _client = DivarClient(DATA_DIR)
    return _client


def enabled_filters(config: dict[str, Any], filter_ids: list[str] | None = None) -> list[dict[str, Any]]:
    specs = list(config.get("filters") or [])
    if filter_ids:
        wanted = set(filter_ids)
        specs = [spec for spec in specs if spec.get("id") in wanted]
        missing = wanted - {spec.get("id") for spec in specs}
        if missing:
            raise AppError("One of the selected filters was not found.")
    return [spec for spec in specs if spec.get("enabled", True)]


def build_notifier(config: dict[str, Any], dry_run: bool) -> TelegramNotifier | None:
    if dry_run:
        return None
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise AppError(
            "Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."
        )
    telegram = config.get("telegram") or {}
    return TelegramNotifier(
        bot_token=token,
        chat_id=chat_id,
        send_photos=bool(telegram.get("send_photos", True)),
        delay_seconds=float(telegram.get("delay_seconds", 0.8)),
    )


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


def deliver(
    listings: list[Listing],
    store: SeenStore,
    notifier: TelegramNotifier | None,
    *,
    max_send: int,
    send_on_first_run: bool,
) -> dict[str, Any]:
    first_run = not store.path.exists()
    fresh = [item for item in listings if store.is_new(item.token)]
    if first_run and not send_on_first_run:
        if notifier is not None:
            store.add_many([item.token for item in listings])
        return {
            "sent": 0,
            "found": len(listings),
            "new": len(fresh),
            "message": f"First run: saved {len(listings)} listings without sending.",
            "listings": [],
        }

    to_send = fresh[:max_send] if max_send > 0 else fresh
    if not to_send:
        return {
            "sent": 0,
            "found": len(listings),
            "new": 0,
            "message": "No new listings.",
            "listings": [],
        }

    sent_items: list[Listing] = []
    for item in to_send:
        if notifier is not None:
            notifier.send_listing(item)
        sent_items.append(item)
    if notifier is not None:
        store.add_many([item.token for item in to_send])

    leftover = len(fresh) - len(to_send)
    message = f"Sent {len(to_send)} listings."
    if leftover > 0:
        message += f" {leftover} left for later."
    return {
        "sent": len(to_send),
        "found": len(listings),
        "new": len(fresh),
        "message": message,
        "listings": [item.to_dict() for item in sent_items],
    }


def preview_spec(body: dict[str, Any], limit: int = 24) -> dict[str, Any]:
    if body.get("id") and len(body) <= 2:
        spec = get_filter(str(body["id"]))
    else:
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


def best_count(config: dict[str, Any] | None = None) -> int:
    config = config or load_config()
    if config.get("best_count") is not None:
        return max(1, min(int(config["best_count"]), 10))
    return max(1, min(int(config.get("max_send_per_run") or 5), 10))


def send_best(count: int | None = None, filter_ids: list[str] | None = None) -> dict[str, Any]:
    config = load_config()
    specs = enabled_filters(config, filter_ids)
    if not specs:
        raise AppError("No enabled filters to run.")
    listings = collect_listings(specs)
    wanted = count if count is not None else best_count(config)
    chosen, source = pick_best_ai(listings, wanted)
    notifier = build_notifier(config, dry_run=False)
    assert notifier is not None
    if not chosen:
        notifier.send_text("آگهی مناسبی با فیلترهای فعال پیدا نشد.")
        return {"sent": 0, "found": 0, "listings": [], "message": "No matching listings."}
    label = "با مدل زبانی" if source == "ai" else "با رتبه‌بندی ساده"
    notifier.send_text(f"{len(chosen)} آگهی برتر از {len(listings)} آگهی فعال ({label}):")
    for index, (item, reason) in enumerate(chosen, start=1):
        notifier.send_listing(item, rank=index, reason=reason)
    return {
        "sent": len(chosen),
        "found": len(listings),
        "source": source,
        "listings": [item.to_dict() for item, _reason in chosen],
        "message": f"Sent top {len(chosen)} of {len(listings)} listings ({source}).",
        "filters": [spec.get("name") for spec in specs],
    }


def watch_tick() -> dict[str, Any]:
    config = load_config()
    specs = enabled_filters(config)
    if not specs:
        raise AppError("No enabled filters to run.")
    listings = collect_listings(specs)
    max_age = max(1, poll_interval_seconds(config) // 60)
    newest = [
        item
        for item in listings
        if item.age_minutes is not None and item.age_minutes <= max_age
    ]
    store = SeenStore(DATA_DIR / "seen.json")
    notifier = build_notifier(config, dry_run=False)
    result = deliver(
        newest,
        store,
        notifier,
        max_send=0,
        send_on_first_run=True,
    )
    result["filters"] = [spec.get("name") for spec in specs]
    result["found_all"] = len(listings)
    if result["sent"] == 0 and not result.get("new"):
        result["message"] = f"No new listings in the last {max_age} min."
    return result
