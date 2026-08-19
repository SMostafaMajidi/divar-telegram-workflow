from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
DATA_DIR = ROOT / "data"
ENV_PATH = ROOT / ".env"
# Iran is permanently UTC+3:30; slots are aligned to local midnight.
APP_TZ = timezone(timedelta(hours=3, minutes=30))


class AppError(Exception):
    pass


def load_dotenv(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def upsert_env_value(key: str, value: str, path: Path = ENV_PATH) -> None:
    lines: list[str] = []
    found = False
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise AppError("config.yaml was not found.")
    with path.open(encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    if _ensure_filter_ids(config):
        save_config(config, path)
    return config


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def save_config(config: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    dumped = yaml.dump(
        config,
        Dumper=_Dumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Filters can also be edited in the web UI at http://127.0.0.1:8765\n" + dumped,
        encoding="utf-8",
    )


def _ensure_filter_ids(config: dict[str, Any]) -> bool:
    changed = False
    filters = config.setdefault("filters", [])
    seen: set[str] = set()
    for spec in filters:
        fid = str(spec.get("id") or "").strip()
        if not fid or fid in seen:
            spec["id"] = uuid.uuid4().hex[:10]
            changed = True
            fid = spec["id"]
        seen.add(fid)
    return changed


def filter_to_api(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": spec.get("id"),
        "name": spec.get("name") or "",
        "enabled": spec.get("enabled", True),
        "category": spec.get("category") or "light",
        "query": spec.get("query") or "",
        "cities": list(spec.get("cities") or []),
        "price_min_million": _to_million(spec.get("price_min_toman")),
        "price_max_million": _to_million(spec.get("price_max_toman")),
        "exclude_title": list(spec.get("exclude_title") or []),
        "max_pages": int(spec.get("max_pages") or 3),
        "chat_id": str(spec.get("chat_id") or "").strip(),
    }


def filter_from_api(body: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = dict(existing or {})
    spec["id"] = str(body.get("id") or spec.get("id") or uuid.uuid4().hex[:10])
    name = str(body.get("name") or "").strip()
    query = str(body.get("query") or "").strip()
    if not name:
        raise AppError("Enter a filter name.")
    if not query:
        raise AppError("Enter a search query, e.g. Pride.")
    cities = _clean_list(body.get("cities"))
    if not cities:
        raise AppError("Select at least one city.")
    spec.update(
        {
            "name": name,
            "enabled": bool(body.get("enabled", True)),
            "category": str(body.get("category") or "light").strip() or "light",
            "query": query,
            "cities": cities,
            "price_min_toman": _from_million(body.get("price_min_million")),
            "price_max_toman": _from_million(body.get("price_max_million")),
            "exclude_title": _clean_list(body.get("exclude_title")),
            "max_pages": max(1, min(int(body.get("max_pages") or 3), 8)),
            "chat_id": str(body.get("chat_id") if "chat_id" in body else spec.get("chat_id") or "").strip(),
        }
    )
    return spec


def upsert_filter(body: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    filters = config.setdefault("filters", [])
    incoming_id = str(body.get("id") or "").strip()
    existing = next((f for f in filters if f.get("id") == incoming_id), None) if incoming_id else None
    spec = filter_from_api(body, existing)
    if existing is None:
        filters.append(spec)
    else:
        index = filters.index(existing)
        filters[index] = spec
    save_config(config)
    return filter_to_api(spec)


def delete_filter(filter_id: str) -> None:
    config = load_config()
    filters = config.get("filters") or []
    kept = [f for f in filters if f.get("id") != filter_id]
    if len(kept) == len(filters):
        raise AppError("Filter not found.")
    config["filters"] = kept
    save_config(config)


def toggle_filter(filter_id: str, enabled: bool | None = None) -> dict[str, Any]:
    config = load_config()
    for spec in config.get("filters") or []:
        if spec.get("id") == filter_id:
            spec["enabled"] = (not spec.get("enabled", True)) if enabled is None else bool(enabled)
            save_config(config)
            return filter_to_api(spec)
    raise AppError("Filter not found.")


def set_filter_chat(filter_id: str, chat_id: str | None) -> dict[str, Any]:
    config = load_config()
    for spec in config.get("filters") or []:
        if spec.get("id") == filter_id:
            spec["chat_id"] = str(chat_id or "").strip()
            save_config(config)
            return filter_to_api(spec)
    raise AppError("Filter not found.")


def detect_telegram_chat(chat_id: str | int | None = None) -> dict[str, Any]:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise AppError("Bot token is missing from .env.")
    from notifier import telegram_bot_username

    chats = list_saved_chats()
    if chat_id not in (None, ""):
        chosen = str(chat_id)
        upsert_env_value("TELEGRAM_CHAT_ID", chosen)
        return {"chat_id": chosen, "chats": chats, "saved": True}

    if not chats:
        username = telegram_bot_username(token) or "the bot"
        raise AppError(
            f"No chat yet. Open @{username} in Telegram, send /start, then refresh the chat list."
        )
    if len(chats) == 1:
        chosen = str(chats[0]["id"])
        upsert_env_value("TELEGRAM_CHAT_ID", chosen)
        return {"chat_id": chosen, "chats": chats, "saved": True}
    return {"chat_id": None, "chats": chats, "saved": False}


def list_saved_chats() -> list[dict[str, Any]]:
    load_dotenv()
    from store import ChatStore

    chats = {item["id"]: item for item in ChatStore(DATA_DIR / "chats.json").all()}
    default_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if default_id and default_id not in chats:
        chats[default_id] = {
            "id": default_id,
            "type": "private",
            "name": "چت پیش‌فرض",
            "username": "",
        }
    elif default_id and chats[default_id] and not chats[default_id].get("name"):
        chats[default_id]["name"] = "چت پیش‌فرض"
    return sorted(chats.values(), key=lambda item: (item.get("name") or item["id"]))


def get_filter(filter_id: str) -> dict[str, Any]:
    config = load_config()
    for spec in config.get("filters") or []:
        if spec.get("id") == filter_id:
            return spec
    raise AppError("Filter not found.")


def update_settings(body: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    minutes = body.get("poll_interval_minutes", body.get("poll_interval_seconds"))
    if minutes is not None:
        if "poll_interval_seconds" in body and "poll_interval_minutes" not in body:
            minutes = max(1, round(int(minutes) / 60))
        config["poll_interval_minutes"] = max(1, int(minutes))
        config.pop("poll_interval_seconds", None)
    if "best_count" in body:
        config["best_count"] = max(1, min(int(body["best_count"]), 10))
    if "max_send_per_run" in body:
        config["max_send_per_run"] = max(1, int(body["max_send_per_run"]))
    if "send_on_first_run" in body:
        config["send_on_first_run"] = bool(body["send_on_first_run"])
    telegram = config.setdefault("telegram", {})
    if "send_photos" in body:
        telegram["send_photos"] = bool(body["send_photos"])
    save_config(config)
    return public_settings(config)


def poll_interval_seconds(config: dict[str, Any] | None = None) -> int:
    config = config or load_config()
    if config.get("poll_interval_minutes") is not None:
        return max(1, int(config["poll_interval_minutes"])) * 60
    if config.get("poll_interval_seconds") is not None:
        return max(60, int(config["poll_interval_seconds"]))
    return 180


def seconds_until_next_slot(
    interval_seconds: int | None = None,
    *,
    now: datetime | None = None,
    include_now: bool = False,
) -> float:
    interval = max(1, int(interval_seconds if interval_seconds is not None else poll_interval_seconds()))
    current = now.astimezone(APP_TZ) if now else datetime.now(APP_TZ)
    midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (current - midnight).total_seconds()
    remainder = elapsed % interval
    if include_now and remainder < 1:
        return 0.0
    if remainder < 1e-6:
        return float(interval)
    return float(interval - remainder)


def next_slot_at(
    interval_seconds: int | None = None,
    *,
    now: datetime | None = None,
    include_now: bool = False,
) -> datetime:
    current = now.astimezone(APP_TZ) if now else datetime.now(APP_TZ)
    wait = seconds_until_next_slot(interval_seconds, now=current, include_now=include_now)
    return current + timedelta(seconds=wait)


def format_slot_time(when: datetime | None = None) -> str:
    when = when or next_slot_at(include_now=True)
    return when.astimezone(APP_TZ).strftime("%H:%M")


def public_settings(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    load_dotenv()
    filters = config.get("filters") or []
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    from notifier import telegram_bot_username
    seconds = poll_interval_seconds(config)
    return {
        "poll_interval_minutes": max(1, seconds // 60),
        "best_count": max(1, min(int(config.get("best_count") or config.get("max_send_per_run") or 5), 10)),
        "max_send_per_run": int(config.get("max_send_per_run") or 25),
        "send_on_first_run": bool(config.get("send_on_first_run", True)),
        "send_photos": bool((config.get("telegram") or {}).get("send_photos", True)),
        "telegram_token": bool(token),
        "telegram_chat": bool(chat_id) or any(str(f.get("chat_id") or "").strip() for f in filters),
        "telegram_ready": bool(token and (chat_id or any(str(f.get("chat_id") or "").strip() for f in filters))),
        "default_chat_id": chat_id,
        "bot_username": telegram_bot_username(token) if token else None,
        "llm_ready": bool((os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()),
        "llm_model": (os.getenv("LLM_MODEL") or "gpt-4o-mini").strip(),
        "filter_count": len(filters),
        "enabled_count": sum(1 for f in filters if f.get("enabled", True)),
    }


def _to_million(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    number = int(value) / 1_000_000
    return int(number) if number == int(number) else number


def _from_million(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(round(float(value) * 1_000_000))


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.replace("،", ",").split(",")
        return [p.strip() for p in parts if p.strip()]
    return [str(item).strip() for item in value if str(item).strip()]
