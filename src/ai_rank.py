from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from divar import Listing
from rank import listing_year, parse_int, pick_best

MAX_CANDIDATES = 50


def llm_api_key() -> str:
    return (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()


def llm_base_url() -> str:
    return (os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")


def llm_model() -> str:
    return (os.getenv("LLM_MODEL") or "gpt-4o-mini").strip()


def llm_ready() -> bool:
    return bool(llm_api_key())


def pick_best_ai(listings: list[Listing], count: int) -> tuple[list[tuple[Listing, str]], str]:
    """Return (picks with reasons, source: ai|heuristic)."""
    wanted = max(1, min(int(count), 10))
    if not listings:
        return [], "heuristic"
    fallback = [(item, "") for item in pick_best(listings, wanted)]
    if not llm_ready():
        return fallback, "heuristic"
    try:
        chosen = _ask_model(listings, wanted)
    except Exception:
        return fallback, "heuristic"
    if not chosen:
        return fallback, "heuristic"
    return chosen, "ai"


def _ask_model(listings: list[Listing], count: int) -> list[tuple[Listing, str]]:
    candidates = listings[:MAX_CANDIDATES]
    by_token = {item.token: item for item in candidates}
    payload = {
        "model": llm_model(),
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "تو مشاور خرید خودروی کارکرده در ایران هستی. "
                    "فقط از بین همین آگهی‌ها انتخاب کن. "
                    "معیارها: عکس واقعی، مدل جدیدتر، کارکرد معقول "
                    "(۰ و ۱۱۱۱۱۱ و عددهای ساختگی بد است)، قیمت منصفانه نسبت به سال و کارکرد، "
                    "شهر، تازگی آگهی، و نشانه‌های تصادف/شاسی/رنگ/اسقاط/موتورسوخته در عنوان. "
                    "آگهی مشکوک یا آسیب‌دیده را کنار بگذار. "
                    f"دقیقاً تا {count} مورد برتر را به ترتیب اولویت برگردان. "
                    "خروجی فقط JSON با این شکل باشد: "
                    '{"picks":[{"token":"...","reason":"یک جمله فارسی"}]}'
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    [_listing_payload(item) for item in candidates],
                    ensure_ascii=False,
                ),
            },
        ],
    }
    url = f"{llm_base_url()}/chat/completions"
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {llm_api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://127.0.0.1:8765",
            "X-Title": "Divar watcher",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    content = (((response.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    picks = _parse_picks(content)
    out: list[tuple[Listing, str]] = []
    seen: set[str] = set()
    for row in picks:
        token = str(row.get("token") or "").strip()
        if not token or token in seen or token not in by_token:
            continue
        seen.add(token)
        reason = str(row.get("reason") or "").strip()[:180]
        out.append((by_token[token], reason))
        if len(out) >= count:
            break
    return out


def _listing_payload(item: Listing) -> dict[str, Any]:
    return {
        "token": item.token,
        "title": item.title,
        "price": item.price,
        "mileage": item.mileage,
        "year": listing_year(item.title) or None,
        "km": parse_int(item.mileage),
        "city": item.location,
        "has_photo": bool(item.image_url),
        "age": item.age_text,
        "url": item.url,
    }


def _parse_picks(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if match:
        text = match.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return []
    data = json.loads(text[start : end + 1])
    picks = data.get("picks") if isinstance(data, dict) else None
    if not isinstance(picks, list):
        return []
    return [row for row in picks if isinstance(row, dict)]
