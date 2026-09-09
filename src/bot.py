from __future__ import annotations

import re
import threading
import time

from config_store import AppError, load_config, load_dotenv, public_base_url
from messengers import CHANNEL_LABELS, build_messenger
from notifier import chat_record
from runner import best_count, send_best_for_user
import db

HELP = (
    "به دیوار واچر خوش آمدید.\n\n"
    "شروع سریع:\n"
    "۱) /start و ساخت یوزرنیم/رمز پنل (یا /login برای اتصال حساب موجود)\n"
    "۲) ورود به پنل وب و ساخت فیلتر\n"
    "۳) انتخاب یک یا چند مقصد ارسال برای هر فیلتر\n"
    "۴) در صورت نیاز خرید پلن از صفحه قیمت\n\n"
    "دستورها:\n"
    "• /start — ثبت‌نام یا وضعیت حساب\n"
    "• /login — اتصال حساب وب به این چت\n"
    "• /cancel — لغو\n"
    "• لینک پنل — آدرس ورود وب\n"
    "• ۵ تا بهترین / /best — در صورت فعال بودن هوش مصنوعی\n\n"
    f"پلن‌ها: {public_base_url()}/pricing\n"
    f"پشتیبانی: {public_base_url()}/support"
)

KEYBOARD = {
    "keyboard": [[{"text": "لینک پنل"}], [{"text": "۵ تا بهترین"}]],
    "resize_keyboard": True,
}

_pending_lock = threading.Lock()
_pending: dict[str, dict] = {}


class MessengerBot:
    def __init__(self, channel: str = "telegram") -> None:
        self.channel = str(channel or "telegram").strip().lower() or "telegram"
        self.running = False
        self.last_message = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = 0

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name=f"bot-{self.channel}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.running = False

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                notifier = build_messenger(self.channel, load_config())
                self._poll(notifier)
            except AppError as exc:
                self.last_message = str(exc)
                if self._stop.wait(5):
                    break
            except Exception as exc:
                self.last_message = str(exc)
                if self._stop.wait(3):
                    break

    def _poll(self, notifier) -> None:
        try:
            backlog = notifier.get_updates(offset=self._offset, timeout=0)
            for update in backlog:
                self._offset = int(update.get("update_id") or 0) + 1
        except Exception:
            pass
        while not self._stop.is_set():
            try:
                updates = notifier.get_updates(offset=self._offset, timeout=25)
            except Exception as exc:
                self.last_message = str(exc)
                time.sleep(2)
                continue
            for update in updates:
                self._offset = int(update.get("update_id") or 0) + 1
                if self.channel == "bale" and update.get("pre_checkout_query"):
                    self._handle_pre_checkout(notifier, update["pre_checkout_query"])
                    continue
                self._remember_chats(update)
                message = (
                    update.get("message")
                    or update.get("edited_message")
                    or update.get("channel_post")
                    or {}
                )
                if self.channel == "bale" and message.get("successful_payment"):
                    self._handle_successful_payment(notifier, message)
                    continue
                chat_id = str((message.get("chat") or {}).get("id") or "")
                text = str(message.get("text") or "").strip()
                if not chat_id or not text:
                    continue
                self._handle(notifier, text, chat_id, message)

    def _handle_pre_checkout(self, notifier, query: dict) -> None:
        try:
            from bale_payments import handle_pre_checkout_query

            handle_pre_checkout_query(notifier, query)
            self.last_message = "pre_checkout ok"
        except Exception as exc:
            self.last_message = f"pre_checkout: {exc}"

    def _handle_successful_payment(self, notifier, message: dict) -> None:
        chat_id = str((message.get("chat") or {}).get("id") or "")
        try:
            from bale_payments import handle_successful_payment

            result = handle_successful_payment(message)
            if not result:
                if chat_id:
                    notifier.send_text("پرداخت دریافت شد ولی فاکتور پیدا نشد.", chat_id=chat_id)
                return
            inv = result.get("invoice") or {}
            plan = inv.get("plan_name") or inv.get("plan_id") or ""
            if chat_id:
                notifier.send_text(
                    f"پرداخت موفق بود. پلن «{plan}» فعال شد.\n"
                    f"صورتحساب: {public_base_url()}/app/billing",
                    chat_id=chat_id,
                )
            self.last_message = f"wallet paid {inv.get('id')}"
        except Exception as exc:
            self.last_message = f"successful_payment: {exc}"
            if chat_id:
                try:
                    notifier.send_text(
                        "پرداخت انجام شد ولی فعال‌سازی خودکار با خطا مواجه شد. با پشتیبانی هماهنگ کنید.",
                        chat_id=chat_id,
                    )
                except Exception:
                    pass

    def _remember_chats(self, update: dict) -> None:
        record = chat_record(
            (
                (update.get("message") or {}).get("chat")
                or (update.get("edited_message") or {}).get("chat")
                or (update.get("channel_post") or {}).get("chat")
                or (update.get("my_chat_member") or {}).get("chat")
            )
        )
        if not record:
            return
        user = None
        # Prefer chat already linked as the user's private chat.
        user = db.get_user_by_messenger_account(self.channel, record["id"]) or (
            db.get_user_by_chat_id(record["id"]) if self.channel == "telegram" else None
        )
        if not user:
            sender = (
                (update.get("message") or {}).get("from")
                or (update.get("edited_message") or {}).get("from")
                or (update.get("my_chat_member") or {}).get("from")
                or {}
            )
            username = str(sender.get("username") or "").strip()
            if username:
                user = db.get_user_by_username(username)
        if not user:
            return
        try:
            db.upsert_user_chat(
                user["id"],
                channel=self.channel,
                chat_id=record["id"],
                chat_type=record.get("type") or "",
                name=record.get("name") or "",
                username=record.get("username") or "",
            )
        except Exception:
            pass

    def _handle(
        self,
        notifier,
        text: str,
        chat_id: str,
        message: dict,
    ) -> None:
        command = text.strip()
        lowered = command.lower().split("@", 1)[0]

        if lowered in {"/cancel", "cancel", "لغو"}:
            _clear_pending(chat_id)
            notifier.send_text("ثبت‌نام لغو شد. برای شروع دوباره /start بزنید.", chat_id=chat_id)
            return

        pending = _get_pending(chat_id)
        if pending:
            if pending.get("mode") == "login":
                self._continue_login(notifier, chat_id, message, command, pending)
            else:
                self._continue_register(notifier, chat_id, message, command, pending)
            return

        parts = lowered.split(maxsplit=1)
        start_cmd = parts[0] if parts else ""
        start_payload = parts[1] if len(parts) > 1 else ""

        if start_cmd in {"/start", "/help", "help", "راهنما"}:
            if start_payload in {"link", "login"} or start_payload.startswith("link"):
                self._begin_login(notifier, chat_id, message)
                return
            self._start(notifier, chat_id, message)
            return
        if lowered in {"/login", "login", "ورود"}:
            self._begin_login(notifier, chat_id, message)
            return
        if lowered in {"/resetpass", "resetpass"}:
            _set_pending(chat_id, {"step": "username", "reset": True})
            notifier.send_text(
                "یوزرنیم جدید ورود را بفرستید (یا /cancel):",
                chat_id=chat_id,
            )
            return
        if lowered in {"لینک پنل", "/portal"}:
            self._send_portal_link(notifier, chat_id)
            return

        user = db.get_user_by_messenger_account(self.channel, chat_id) or (
            db.get_user_by_chat_id(chat_id) if self.channel == "telegram" else None
        )
        count = _requested_count(command, user)
        if count is None:
            notifier.send_text(
                "برای مدیریت فیلترها وارد پنل وب شوید. «لینک پنل» را بفرستید.\n"
                "برای آگهی‌های برتر (در صورت فعال بودن): «۵ تا بهترین» یا /best",
                reply_markup=KEYBOARD,
                chat_id=chat_id,
            )
            return
        if not user:
            notifier.send_text("ابتدا /start بزنید و ثبت‌نام کنید.", chat_id=chat_id)
            return
        if not user.get("ai_enabled"):
            notifier.send_text(
                "رتبه‌بندی هوشمند برای حساب شما فعال نیست. از پشتیبانی درخواست کنید.",
                chat_id=chat_id,
            )
            return
        notifier.send_text("در حال بررسی آگهی‌های فعال…", chat_id=chat_id)
        try:
            result = send_best_for_user(
                user,
                count,
                reply_channel=self.channel,
                reply_chat_id=chat_id,
            )
            self.last_message = result["message"]
        except Exception as exc:
            self.last_message = str(exc)
            notifier.send_text("جستجو با مشکل مواجه شد. کمی بعد دوباره تلاش کنید.", chat_id=chat_id)

    def _start(self, notifier, chat_id: str, message: dict) -> None:
        user = db.get_user_by_messenger_account(self.channel, chat_id) or (
            db.get_user_by_chat_id(chat_id) if self.channel == "telegram" else None
        )
        login_url = public_base_url()
        label = CHANNEL_LABELS.get(self.channel, self.channel)
        if user and user.get("has_password") and user.get("login_username"):
            try:
                db.link_messenger_account(
                    user["id"],
                    channel=self.channel,
                    account_id=chat_id,
                    username=user.get("telegram_username") or "",
                    display_name=user.get("display_name") or "",
                )
            except Exception:
                try:
                    db.upsert_user_chat(
                        user["id"],
                        channel=self.channel,
                        chat_id=chat_id,
                        chat_type=str((message.get("chat") or {}).get("type") or "private"),
                        name=user.get("display_name") or user.get("login_username") or "",
                        username=user.get("telegram_username") or "",
                    )
                except Exception:
                    pass
            notifier.send_text(
                f"حساب شما فعال است ({label}).\n"
                f"یوزرنیم ورود: `{user['login_username']}`\n"
                f"ورود به پنل:\n{login_url}\n\n"
                "فیلتر بسازید و چند مقصد ارسال انتخاب کنید.\n"
                "برای افزودن گروه/کانال: ربات را آنجا ادمین کنید و یک پیام بفرستید.\n"
                "اتصال حساب وب: /login\n"
                "تغییر یوزرنیم/رمز: /resetpass",
                reply_markup=KEYBOARD,
                chat_id=chat_id,
            )
            return

        _set_pending(chat_id, {"step": "username", "reset": bool(user), "channel": self.channel})
        notifier.send_text(
            f"ثبت‌نام دیوار واچر ({label})\n\n"
            "یوزرنیم ورود به پنل را بفرستید "
            "(انگلیسی، عدد و _ ، حداقل ۳ کاراکتر).\n"
            "اگر قبلاً در سایت ثبت‌نام کرده‌اید /login بزنید.\n"
            "برای لغو: /cancel",
            chat_id=chat_id,
        )

    def _begin_login(self, notifier, chat_id: str, message: dict) -> None:
        _set_pending(chat_id, {"mode": "login", "step": "username", "channel": self.channel})
        notifier.send_text(
            "یوزرنیم ورود سایت را بفرستید تا این چت به حساب‌تان وصل شود:\n(یا /cancel)",
            chat_id=chat_id,
        )

    def _continue_login(
        self,
        notifier,
        chat_id: str,
        message: dict,
        command: str,
        pending: dict,
    ) -> None:
        step = pending.get("step")
        label = CHANNEL_LABELS.get(self.channel, self.channel)
        if step == "username":
            try:
                login = db.normalize_login_username(command)
            except Exception as exc:
                notifier.send_text(str(exc), chat_id=chat_id)
                return
            _set_pending(chat_id, {**pending, "step": "password", "login_username": login})
            notifier.send_text("رمز عبور پنل را بفرستید:", chat_id=chat_id)
            return
        if step == "password":
            login = str(pending.get("login_username") or "")
            sender = message.get("from") or {}
            try:
                user = db.link_messenger_by_login(
                    channel=self.channel,
                    account_id=chat_id,
                    login_username=login,
                    password=command,
                    username=str(sender.get("username") or ""),
                    display_name=str(sender.get("first_name") or ""),
                )
            except Exception as exc:
                notifier.send_text(str(exc), chat_id=chat_id)
                return
            _clear_pending(chat_id)
            notifier.send_text(
                f"اتصال برقرار شد ✅\n"
                f"حساب @{user.get('login_username')} به {label} لینک شد.\n"
                f"پنل:\n{public_base_url()}",
                reply_markup=KEYBOARD,
                chat_id=chat_id,
            )
            self.last_message = (
                f"Linked @{user.get('login_username')} channel={self.channel} chat={chat_id}"
            )
            return
        _clear_pending(chat_id)
        notifier.send_text("ورود نامعتبر بود. دوباره /login بزنید.", chat_id=chat_id)

    def _continue_register(
        self,
        notifier,
        chat_id: str,
        message: dict,
        text: str,
        pending: dict,
    ) -> None:
        step = pending.get("step")
        if step == "username":
            try:
                login = db.normalize_login_username(text)
            except AppError as exc:
                notifier.send_text(str(exc), chat_id=chat_id)
                return
            _set_pending(chat_id, {**pending, "step": "password", "login_username": login})
            notifier.send_text("رمز عبور را بفرستید (حداقل ۴ کاراکتر):", chat_id=chat_id)
            return

        if step == "password":
            login = pending.get("login_username") or ""
            from_user = message.get("from") or {}
            tg_username = str(from_user.get("username") or "").strip()
            display = str(from_user.get("first_name") or "").strip()
            try:
                if self.channel == "telegram":
                    user = db.register_from_telegram(
                        login_username=login,
                        password=text,
                        chat_id=chat_id,
                        telegram_username=tg_username,
                        display_name=display,
                    )
                else:
                    placeholder = f"{self.channel}_{chat_id}"[-32:]
                    user = db.create_user(
                        placeholder,
                        display_name=display or login,
                        login_username=login,
                        password=text,
                    )
                    user = db.link_messenger_account(
                        user["id"],
                        channel=self.channel,
                        account_id=chat_id,
                        username=tg_username,
                        display_name=display or login,
                    )
            except AppError as exc:
                notifier.send_text(str(exc), chat_id=chat_id)
                return
            _clear_pending(chat_id)
            login_url = public_base_url()
            try:
                db.upsert_user_chat(
                    user["id"],
                    channel=self.channel,
                    chat_id=chat_id,
                    chat_type=str((message.get("chat") or {}).get("type") or "private"),
                    name=user.get("display_name") or user.get("login_username") or "",
                    username=tg_username or user.get("telegram_username") or "",
                )
            except Exception:
                pass
            notifier.send_text(
                "ثبت‌نام انجام شد.\n\n"
                f"یوزرنیم: `{user['login_username']}`\n"
                f"ورود به پنل:\n{login_url}\n\n"
                "در پنل فیلتر بسازید و مقصدهای ارسال را انتخاب کنید.\n"
                "برای افزودن گروه/کانال: ربات را عضو کنید و یک پیام بفرستید.",
                reply_markup=KEYBOARD,
                chat_id=chat_id,
            )
            self.last_message = (
                f"Registered @{user['login_username']} channel={self.channel} chat={chat_id}"
            )
            return

        _clear_pending(chat_id)
        notifier.send_text("ثبت‌نام نامعتبر بود. دوباره /start بزنید.", chat_id=chat_id)

    def _send_portal_link(self, notifier, chat_id: str) -> None:
        user = db.get_user_by_messenger_account(self.channel, chat_id) or (
            db.get_user_by_chat_id(chat_id) if self.channel == "telegram" else None
        )
        login_url = public_base_url()
        if not user or not user.get("has_password"):
            notifier.send_text("ابتدا /start بزنید و یوزرنیم/رمز را تنظیم کنید.", chat_id=chat_id)
            return
        notifier.send_text(
            f"ورود به پنل با یوزرنیم `{user['login_username']}`:\n{login_url}",
            chat_id=chat_id,
        )


TelegramBot = MessengerBot


def _get_pending(chat_id: str) -> dict | None:
    with _pending_lock:
        return dict(_pending[chat_id]) if chat_id in _pending else None


def _set_pending(chat_id: str, data: dict) -> None:
    with _pending_lock:
        _pending[chat_id] = data


def _clear_pending(chat_id: str) -> None:
    with _pending_lock:
        _pending.pop(chat_id, None)


def _requested_count(text: str, user: dict | None = None) -> int | None:
    raw = text.strip().lower().replace("\u200c", "").translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    )
    raw = raw.replace("/", " ").split("@", 1)[0].strip()
    if raw in {"best", "top", "بهترین", "5 تا بهترین", "پنج تا بهترین"}:
        return best_count(user=user)
    match = re.fullmatch(r"(?:best|top|بهترین)\s+(\d{1,2})", raw)
    if match:
        return max(1, min(int(match.group(1)), 10))
    match = re.fullmatch(r"(\d{1,2})\s*(?:تا)?\s*بهترین", raw)
    if match:
        return max(1, min(int(match.group(1)), 10))
    return None


def run_bot() -> None:
    load_dotenv()
    bot = MessengerBot("telegram")
    print("Telegram bot listening")
    bot.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bot.stop()
        print("\nStopped.")
