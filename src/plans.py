from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def format_toman(amount: int | None) -> str:
    value = int(amount or 0)
    if value <= 0:
        return "رایگان"
    grouped = f"{value:,}".replace(",", "٬").translate(PERSIAN_DIGITS)
    return f"{grouped} تومان / ماه"


PLANS: dict[str, dict[str, Any]] = {
    "trial": {
        "id": "trial",
        "name": "آزمایشی",
        "tagline": "۷ روز برای تست واقعی",
        "price_toman": 0,
        "max_filters": 1,
        "poll_interval_minutes": 5,
        "ai_enabled": False,
        "duration_days": 7,
        "features": ["۱ فیلتر فعال", "پایش هر ۵ دقیقه", "ارسال به تلگرام"],
        "api_access": False,
    },
    "basic": {
        "id": "basic",
        "name": "پایه",
        "tagline": "برای پیگیری روزانه آگهی",
        "price_toman": 490_000,
        "max_filters": 3,
        "poll_interval_minutes": 5,
        "ai_enabled": False,
        "duration_days": 30,
        "features": ["۳ فیلتر فعال", "پایش هر ۵ دقیقه", "مقصد چت جدا برای هر فیلتر"],
        "api_access": False,
    },
    "pro": {
        "id": "pro",
        "name": "حرفه‌ای",
        "tagline": "فیلتر بیشتر + رتبه‌بندی هوشمند + API",
        "price_toman": 990_000,
        "max_filters": 10,
        "poll_interval_minutes": 3,
        "ai_enabled": True,
        "duration_days": 30,
        "features": [
            "۱۰ فیلتر فعال",
            "پایش هر ۳ دقیقه",
            "رتبه‌بندی هوشمند",
            "دسترسی API",
            "اولویت پشتیبانی",
        ],
        "api_access": True,
    },
}


def _with_price(plan: dict[str, Any]) -> dict[str, Any]:
    out = dict(plan)
    out["price_label"] = format_toman(out.get("price_toman"))
    return out


def list_plans() -> list[dict[str, Any]]:
    return [_with_price(PLANS[key]) for key in ("trial", "basic", "pro")]


def get_plan(plan_id: str | None) -> dict[str, Any]:
    key = str(plan_id or "trial").strip().lower() or "trial"
    if key not in PLANS:
        key = "trial"
    return _with_price(PLANS[key])


def parse_expires_at(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def subscription_status(user: dict[str, Any] | None) -> str:
    if not user:
        return "unknown"
    if not user.get("active"):
        return "inactive"
    expires = parse_expires_at(user.get("expires_at"))
    if expires and expires < datetime.now(timezone.utc):
        return "expired"
    plan_id = str(user.get("plan_id") or "trial")
    if plan_id == "trial":
        return "trial"
    return "active"


def subscription_ok(user: dict[str, Any] | None) -> bool:
    return subscription_status(user) in {"trial", "active"}


def effective_max_filters(user: dict[str, Any] | None) -> int:
    if user and user.get("max_filters") is not None:
        return max(0, int(user["max_filters"]))
    return int(get_plan((user or {}).get("plan_id")).get("max_filters") or 1)


def plan_expiry_iso(plan_id: str, *, from_when: datetime | None = None) -> str:
    plan = get_plan(plan_id)
    base = from_when or datetime.now(timezone.utc)
    days = max(1, int(plan.get("duration_days") or 30))
    return (base + timedelta(days=days)).isoformat()


def has_api_access(user: dict[str, Any] | None) -> bool:
    if not user or not subscription_ok(user):
        return False
    plan = get_plan(user.get("plan_id"))
    return bool(plan.get("api_access"))


def paid_plan_ids() -> set[str]:
    return {pid for pid, plan in PLANS.items() if int(plan.get("price_toman") or 0) > 0}
