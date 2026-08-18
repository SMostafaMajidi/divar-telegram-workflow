from __future__ import annotations

import os
import re
import threading
import time

from config_store import AppError, load_config, load_dotenv
from notifier import TelegramNotifier
from runner import best_count, build_notifier, send_best

HELP = (
    "وقتی خواستی بهترین‌ها را ببین، یکی از این‌ها را بزن:\n"
    "• ۵ تا بهترین\n"
    "• /best\n"
    "• /best 5\n\n"
    "پایش جداگانه همه آگهی‌های جدید را می‌فرستد.\n"
    "این دستور فقط ۵ تای برتر را از آگهی‌های فعال می‌آورد."
)

KEYBOARD = {
    "keyboard": [[{"text": "۵ تا بهترین"}]],
    "resize_keyboard": True,
}


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
                notifier = build_notifier(load_config(), dry_run=False)
                assert notifier is not None
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
        allowed = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        try:
            backlog = notifier.get_updates(offset=self._offset, timeout=0)
            if backlog:
                self._offset = int(backlog[-1].get("update_id") or 0) + 1
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
                message = update.get("message") or {}
                chat = (message.get("chat") or {}).get("id")
                if allowed and str(chat) != allowed:
                    continue
                text = str(message.get("text") or "").strip()
                if not text:
                    continue
                self._handle(notifier, text)

    def _handle(self, notifier: TelegramNotifier, text: str) -> None:
        command = text.strip()
        lowered = command.lower()
        if lowered in {"/start", "/help", "help", "راهنما"}:
            notifier.send_text(HELP, reply_markup=KEYBOARD)
            self.last_message = "Sent help."
            return
        count = _requested_count(command)
        if count is None:
            notifier.send_text("برای گرفتن آگهی‌های برتر «۵ تا بهترین» یا /best را بزن.", reply_markup=KEYBOARD)
            return
        notifier.send_text("دارم بین آگهی‌های فعال می‌گردم…")
        try:
            result = send_best(count)
            self.last_message = result["message"]
        except Exception as exc:
            self.last_message = str(exc)
            notifier.send_text("جستجو به مشکل خورد. کمی بعد دوباره بزن.")


def _requested_count(text: str) -> int | None:
    raw = text.strip().lower().replace("\u200c", "").translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    )
    raw = raw.replace("/", " ").strip()
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
    print("Telegram bot listening for /best")
    bot.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bot.stop()
        print("\nStopped.")
