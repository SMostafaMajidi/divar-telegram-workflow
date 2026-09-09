from __future__ import annotations

import os
from typing import Any

from config_store import AppError, load_config, load_dotenv, public_base_url
from messengers import BaleBotClient, build_messenger


def bale_payment_provider_token() -> str:
    load_dotenv()
    return (os.getenv("BALE_PAYMENT_PROVIDER_TOKEN") or "").strip()


def bale_wallet_ready() -> bool:
    load_dotenv()
    return bool((os.getenv("BALE_BOT_TOKEN") or "").strip() and bale_payment_provider_token())


def toman_to_rial(amount_toman: int) -> int:
    return max(0, int(amount_toman or 0) * 10)


def linked_bale_chat_id(user: dict[str, Any] | None) -> str:
    if not user:
        return ""
    for acc in user.get("messenger_accounts") or []:
        if str(acc.get("channel") or "").lower() != "bale":
            continue
        chat_id = str(acc.get("account_id") or "").strip()
        if chat_id:
            return chat_id
    return ""


def _invoice_payload(invoice_id: str) -> str:
    return f"inv:{invoice_id}"


def parse_invoice_payload(payload: str) -> str | None:
    raw = str(payload or "").strip()
    if raw.startswith("inv:"):
        inv_id = raw[4:].strip()
        return inv_id or None
    # Accept bare invoice id for resilience
    if raw and len(raw) <= 32 and all(c.isalnum() for c in raw):
        return raw
    return None


def send_wallet_invoice(user: dict[str, Any], invoice: dict[str, Any]) -> dict[str, Any]:
    import db
    from plans import user_capabilities

    caps = user_capabilities(user)
    if not caps.get("allow_bale_wallet"):
        raise AppError("پلن فعلی شما پرداخت کیف‌پول بله ندارد.")
    if not bale_wallet_ready():
        raise AppError("پرداخت کیف‌پول بله فعال نیست.")
    if not invoice or invoice.get("status") not in {"pending", "awaiting_review"}:
        raise AppError("این فاکتور قابل پرداخت نیست.")
    chat_id = linked_bale_chat_id(user)
    if not chat_id:
        deep = ""
        try:
            client = build_messenger("bale", load_config())
            deep = client.bot_deep_link("link")
        except AppError:
            pass
        hint = f" ابتدا بله را از پنل وصل کنید: {deep}" if deep else " ابتدا حساب بله را در پنل وصل کنید."
        raise AppError("چت بله به حساب شما وصل نیست." + hint)

    amount_rial = toman_to_rial(int(invoice.get("amount_toman") or 0))
    if amount_rial <= 0:
        raise AppError("مبلغ فاکتور نامعتبر است.")

    plan_name = str(invoice.get("plan_name") or "اشتراک").strip() or "اشتراک"
    ref = str(invoice.get("ref_code") or invoice["id"])
    # Bale UI always labels this message type as «درخواست پول» (not customizable).
    # title/description are what we can control — keep them subscription-like.
    title = f"اشتراک {plan_name}"[:32]
    description = (
        f"خرید اشتراک دیوار واچر · پلن {plan_name} · شناسه {ref}"
    )[:255]
    price_label = f"پلن {plan_name}"[:32]
    client = build_messenger("bale", load_config())
    assert isinstance(client, BaleBotClient)
    try:
        client.send_text(
            "فاکتور اشتراک شما آماده است.\n"
            f"پلن: {plan_name}\n"
            f"شناسه: {ref}\n\n"
            "پیام بعدی دکمه پرداخت است (در بله به آن «درخواست پول» می‌گویند).",
            chat_id=chat_id,
        )
    except Exception:
        pass
    result = client.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=_invoice_payload(str(invoice["id"])),
        provider_token=bale_payment_provider_token(),
        prices=[{"label": price_label, "amount": amount_rial}],
    )
    db.mark_invoice_bale_sent(str(invoice["id"]), user["id"])
    username = client.bot_username() or ""
    # Plain bot URL opens the existing chat (where the invoice just arrived).
    open_url = f"https://ble.ir/{username}" if username else client.bot_deep_link("link")
    return {
        "ok": True,
        "chat_id": chat_id,
        "amount_rial": amount_rial,
        "message_id": (result.get("result") or {}).get("message_id"),
        "bot_username": username,
        "open_url": open_url,
        "billing_url": f"{public_base_url()}/app/billing#{invoice['id']}",
    }


def handle_pre_checkout_query(client: BaleBotClient, query: dict[str, Any]) -> None:
    import db

    qid = str(query.get("id") or "")
    if not qid:
        return
    payload = str(query.get("invoice_payload") or "")
    invoice_id = parse_invoice_payload(payload)
    total = int(query.get("total_amount") or 0)
    try:
        if not invoice_id:
            raise AppError("فاکتور نامعتبر است.")
        invoice = db.get_invoice(invoice_id)
        if not invoice:
            raise AppError("فاکتور پیدا نشد.")
        if invoice["status"] not in {"pending", "awaiting_review"}:
            raise AppError("این فاکتور دیگر قابل پرداخت نیست.")
        expected = toman_to_rial(int(invoice.get("amount_toman") or 0))
        if total and expected and total != expected:
            raise AppError("مبلغ پرداخت با فاکتور هم‌خوانی ندارد.")
        payer = query.get("from") or {}
        payer_id = str(payer.get("id") or "").strip()
        if payer_id:
            owner = db.get_user_by_messenger_account("bale", payer_id)
            if owner and owner["id"] != invoice["user_id"]:
                raise AppError("این فاکتور متعلق به حساب دیگری است.")
        client.answer_pre_checkout_query(qid, ok=True)
    except AppError as exc:
        client.answer_pre_checkout_query(qid, ok=False, error_message=str(exc)[:200])
    except Exception:
        client.answer_pre_checkout_query(
            qid, ok=False, error_message="خطای داخلی؛ کمی بعد دوباره تلاش کنید."
        )


def handle_successful_payment(message: dict[str, Any]) -> dict[str, Any] | None:
    import db

    payment = message.get("successful_payment") or {}
    if not payment:
        return None
    invoice_id = parse_invoice_payload(str(payment.get("invoice_payload") or ""))
    if not invoice_id:
        return None
    total = int(payment.get("total_amount") or 0)
    charge = str(
        payment.get("provider_payment_charge_id")
        or payment.get("telegram_payment_charge_id")
        or ""
    ).strip()
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "").strip()
    return db.confirm_invoice_from_wallet(
        invoice_id,
        provider_charge_id=charge,
        total_amount_rial=total or None,
        payer_chat_id=chat_id or None,
    )
