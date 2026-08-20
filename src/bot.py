from __future__ import annotations

import re
import threading
import time

from config_store import AppError, load_config, load_dotenv, public_base_url
from notifier import TelegramNotifier
from runner import best_count, build_notifier, send_best_for_user
import db

HELP = (
    "به دیوار واچر خوش آمدید.\n\n"
    "ثبت‌نام:\n"
    "۱) /start\n"
    "۲) یوزرنیم دلخواه پنل را بفرستید\n"
    "۳) رمز عبور را بفرستید\n"
    "۴) با همان یوزر و رمز وارد پنل وب شوید و فیلتر بسازید.\n\n"
    "دستورها:\n"
    "• /start — ثبت‌نام یا وضعیت حساب\n"
    "• /cancel — لغو ثبت‌نام\n"
    "• لینک پنل — آدرس ورود وب\n"
    "• ۵ تا بهترین / /best — در صورت فعال بودن هوش مصنوعی"
)

KEYBOARD = {
    "keyboard": [[{"text": "لینک پنل"}], [{"text": "۵ تا بهترین"}]],
    "resize_keyboard": True,
}

_pending_lock = threading.Lock()
_pending: dict[str, dict] = {}


class TelegramBot:
    def __init__(self) -> None:
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
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.running = False

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                notifier = build_notifier(load_config(), require_chat=False)
                self._poll(notifier)
            except AppError as exc:
                self.last_message = str(exc)
                if self._stop.wait(5):
                    break
            except Exception as exc:
                self.last_message = str(exc)
                if self._stop.wait(3):
                    break

    def _poll(self, notifier: TelegramNotifier) -> None:
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
                message = (
                    update.get("message")
                    or update.get("edited_message")
                    or update.get("channel_post")
                    or {}
                )
                chat_id = str((message.get("chat") or {}).get("id") or "")
                text = str(message.get("text") or "").strip()
                if not chat_id or not text:
                    continue
                self._handle(notifier, text, chat_id, message)

    def _handle(
        self,
        notifier: TelegramNotifier,
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
            self._continue_register(notifier, chat_id, message, command, pending)
            return

        if lowered in {"/start", "/help", "help", "راهنما"}:
            self._start(notifier, chat_id, message)
            return
        if lowered in {"/resetpass", "resetpass"}:
            _set_pending(chat_id, {"step": "username", "reset": True})
            notifier.send_text(
                "یوزرنیم جدید ورود را بفرستید (یا /cancel):",
                chat_id=chat_id,
            )
            return
        if lowered in {"لینک پنل", "/portal", "/login"}:
            self._send_portal_link(notifier, chat_id)
            return

        user = db.get_user_by_chat_id(chat_id)
        count = _requested_count(command)
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
            result = send_best_for_user(user, count)
            self.last_message = result["message"]
        except Exception as exc:
            self.last_message = str(exc)
            notifier.send_text("جستجو با مشکل مواجه شد. کمی بعد دوباره تلاش کنید.", chat_id=chat_id)

    def _start(self, notifier: TelegramNotifier, chat_id: str, message: dict) -> None:
        user = db.get_user_by_chat_id(chat_id)
        login_url = f"{public_base_url()}/app/login"
        if user and user.get("has_password") and user.get("login_username"):
            notifier.send_text(
                f"حساب شما فعال است.\n"
                f"یوزرنیم ورود: `{user['login_username']}`\n"
                f"ورود به پنل:\n{login_url}\n\n"
                "فیلتر بسازید؛ پایش خودکار آگهی‌های تازه را به همین چت می‌فرستد.\n"
                "برای تغییر یوزرنیم/رمز: /resetpass",
                reply_markup=KEYBOARD,
                chat_id=chat_id,
            )
            return

        _set_pending(chat_id, {"step": "username", "reset": bool(user)})
        notifier.send_text(
            "ثبت‌نام دیوار واچر\n\n"
            "یوزرنیم ورود به پنل را بفرستید "
            "(انگلیسی، عدد و _ ، حداقل ۳ کاراکتر).\n"
            "برای لغو: /cancel",
            chat_id=chat_id,
        )

    def _continue_register(
        self,
        notifier: TelegramNotifier,
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
                user = db.register_from_telegram(
                    login_username=login,
                    password=text,
                    chat_id=chat_id,
                    telegram_username=tg_username,
                    display_name=display,
                )
            except AppError as exc:
                notifier.send_text(str(exc), chat_id=chat_id)
                return
            _clear_pending(chat_id)
            login_url = f"{public_base_url()}/app/login"
            notifier.send_text(
                "ثبت‌نام انجام شد.\n\n"
                f"یوزرنیم: `{user['login_username']}`\n"
                f"ورود به پنل:\n{login_url}\n\n"
                "در پنل فیلتر بسازید؛ آگهی‌های تازه به همین چت ارسال می‌شود.",
                reply_markup=KEYBOARD,
                chat_id=chat_id,
            )
            self.last_message = f"Registered @{user['login_username']} chat={chat_id}"
            return

        _clear_pending(chat_id)
        notifier.send_text("ثبت‌نام نامعتبر بود. دوباره /start بزنید.", chat_id=chat_id)

    def _send_portal_link(self, notifier: TelegramNotifier, chat_id: str) -> None:
        user = db.get_user_by_chat_id(chat_id)
        login_url = f"{public_base_url()}/app/login"
        if not user or not user.get("has_password"):
            notifier.send_text("ابتدا /start بزنید و یوزرنیم/رمز را تنظیم کنید.", chat_id=chat_id)
            return
        notifier.send_text(
            f"ورود به پنل با یوزرنیم `{user['login_username']}`:\n{login_url}",
            chat_id=chat_id,
        )


def _get_pending(chat_id: str) -> dict | None:
    with _pending_lock:
        return dict(_pending[chat_id]) if chat_id in _pending else None


def _set_pending(chat_id: str, data: dict) -> None:
    with _pending_lock:
        _pending[chat_id] = data


def _clear_pending(chat_id: str) -> None:
    with _pending_lock:
        _pending.pop(chat_id, None)


def _requested_count(text: str) -> int | None:
    raw = text.strip().lower().replace("\u200c", "").translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    )
    raw = raw.replace("/", " ").split("@", 1)[0].strip()
    if raw in {"best", "top", "بهترین", "5 تا بهترین", "پنج تا بهترین"}:
        return best_count()
    match = re.fullmatch(r"(?:best|top|بهترین)\s+(\d{1,2})", raw)
    if match:
        return max(1, min(int(match.group(1)), 10))
    match = re.fullmatch(r"(\d{1,2})\s*(?:تا)?\s*بهترین", raw)
    if match:
        return max(1, min(int(match.group(1)), 10))
    return None


def run_bot() -> None:
    load_dotenv()
    bot = TelegramBot()
    print("Telegram bot listening")
    bot.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bot.stop()
        print("\nStopped.")
