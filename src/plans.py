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


DEFAULT_PLANS: dict[str, dict[str, Any]] = {
    "trial": {
        "id": "trial",
        "name": "آزمایشی",
        "tagline": "۷ روز برای تست واقعی",
        "price_toman": 0,
        "max_filters": 1,
        "max_criteria": 1,
        "poll_interval_minutes": 5,
        "ai_enabled": False,
        "duration_days": 7,
        "features": ["۱ فیلتر فعال", "حداکثر ۱ معیار اضافه (مثل قیمت)", "پایش هر ۵ دقیقه"],
        "api_access": False,
        "sort_order": 10,
        "active": True,
    },
    "basic": {
        "id": "basic",
        "name": "پایه",
        "tagline": "برای پیگیری روزانه آگهی",
        "price_toman": 490_000,
        "max_filters": 3,
        "max_criteria": 3,
        "poll_interval_minutes": 5,
        "ai_enabled": False,
        "duration_days": 30,
        "features": ["۳ فیلتر فعال", "تا ۳ معیار روی هر فیلتر", "مقصد چت جدا"],
        "api_access": False,
        "sort_order": 20,
        "active": True,
    },
    "pro": {
        "id": "pro",
        "name": "حرفه‌ای",
        "tagline": "فیلتر بیشتر + رتبه‌بندی هوشمند + API",
        "price_toman": 990_000,
        "max_filters": 10,
        "max_criteria": None,
        "poll_interval_minutes": 3,
        "ai_enabled": True,
        "duration_days": 30,
        "features": [
            "۱۰ فیلتر فعال",
            "معیار نامحدود روی هر فیلتر",
            "رتبه‌بندی هوشمند",
            "دسترسی API",
            "اولویت پشتیبانی",
        ],
        "api_access": True,
        "sort_order": 30,
        "active": True,
    },
}


def _with_price(plan: dict[str, Any]) -> dict[str, Any]:
    out = dict(plan)
    out["price_label"] = format_toman(out.get("price_toman"))
    raw = out.get("max_criteria")
    if raw is None or raw == "" or int(raw or 0) <= 0:
        out["max_criteria"] = None
        out["max_criteria_label"] = "نامحدود"
    else:
        out["max_criteria"] = int(raw)
        out["max_criteria_label"] = str(int(raw))
    return out


def _defaults_list(*, include_inactive: bool = False) -> list[dict[str, Any]]:
    rows = [dict(DEFAULT_PLANS[key]) for key in sorted(DEFAULT_PLANS, key=lambda k: DEFAULT_PLANS[k]["sort_order"])]
    if not include_inactive:
        rows = [r for r in rows if r.get("active", True)]
    return [_with_price(r) for r in rows]


def list_plans(*, include_inactive: bool = False) -> list[dict[str, Any]]:
    try:
        import db

        rows = db.list_plan_rows(include_inactive=include_inactive)
        if rows:
            return [_with_price(r) for r in rows]
    except Exception:
        pass
    return _defaults_list(include_inactive=include_inactive)


def get_plan(plan_id: str | None) -> dict[str, Any]:
    key = str(plan_id or "trial").strip().lower() or "trial"
    try:
        import db

        row = db.get_plan_row(key)
        if row:
            return _with_price(row)
    except Exception:
        pass
    if key in DEFAULT_PLANS:
        return _with_price(dict(DEFAULT_PLANS[key]))
    return _with_price(dict(DEFAULT_PLANS["trial"]))


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


def effective_max_criteria(user: dict[str, Any] | None) -> int | None:
    plan = get_plan((user or {}).get("plan_id"))
    raw = plan.get("max_criteria")
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    # 0 means unlimited (same as empty).
    if value <= 0:
        return None
    return value


def count_filter_criteria(spec: dict[str, Any] | None) -> int:
    """Count selectable constraints (price/year/…); cities & exclude words do not count."""
    if not spec:
        return 0
    count = 0
    if str(spec.get("query") or "").strip():
        count += 1
    fields = dict(spec.get("fields") or {})
    # Legacy price columns count as the price field if not already in fields.
    if "price" not in fields:
        price: dict[str, Any] = {}
        if spec.get("price_min_toman") is not None:
            price["min"] = spec["price_min_toman"]
        if spec.get("price_max_toman") is not None:
            price["max"] = spec["price_max_toman"]
        if price:
            fields["price"] = price
    if "chassis_status" not in fields and spec.get("chassis_status"):
        fields["chassis_status"] = spec["chassis_status"]

    for value in fields.values():
        if value is None or value is False or value == "" or value == [] or value == {}:
            continue
        if isinstance(value, dict):
            if not any(v is not None and v != "" for v in value.values()):
                continue
        count += 1
    return count


def assert_filter_criteria_allowed(user: dict[str, Any] | None, spec: dict[str, Any]) -> None:
    from config_store import AppError

    limit = effective_max_criteria(user)
    if limit is None:
        return
    used = count_filter_criteria(spec)
    if used > limit:
        raise AppError(
            f"سقف معیار این پلن {limit} مورد است (الان {used}). "
            "مثلاً اگر قیمت را گذاشته‌اید، معیار دیگری اضافه نکنید یا پلن بالاتر بگیرید."
        )


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
    return {p["id"] for p in list_plans(include_inactive=True) if int(p.get("price_toman") or 0) > 0}
