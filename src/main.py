from __future__ import annotations

import argparse

from config_store import AppError, detect_telegram_chat, load_config, load_dotenv
from notifier import TelegramNotifier
from runner import build_notifier, send_best


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Search Divar and send listings to Telegram")
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve", "once", "watch", "bot", "test", "chat-id"],
        help="serve web UI, once top ads, watch new ads, bot listen, test, chat-id",
    )
    parser.add_argument("--dry-run", action="store_true", help="print results without sending")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    if args.command == "serve":
        from app import serve

        serve(host=args.host, port=args.port)
        return

    if args.command == "chat-id":
        try:
            result = detect_telegram_chat()
        except AppError as exc:
            raise SystemExit(str(exc)) from exc
        if result.get("saved"):
            print(f"TELEGRAM_CHAT_ID={result['chat_id']}")
        else:
            print("More than one chat found; pick one:")
            for chat in result.get("chats") or []:
                print(f"  {chat['id']}  {chat.get('name')}  ({chat.get('type')})")
        return

    config = load_config()

    if args.command == "test":
        try:
            notifier = build_notifier(config, dry_run=False)
        except AppError as exc:
            raise SystemExit(str(exc)) from exc
        assert isinstance(notifier, TelegramNotifier)
        notifier.send_text("Divar watcher is connected.")
        print("Test message sent.")
        return

    if args.command == "once":
        try:
            result = send_best()
        except AppError as exc:
            raise SystemExit(str(exc)) from exc
        print(result["message"])
        return

    if args.command == "watch":
        from config_store import poll_interval_seconds
        from runner import watch_tick
        import time

        print(f"watching every {poll_interval_seconds(config) // 60} min")
        while True:
            try:
                result = watch_tick()
                print(result["message"])
            except KeyboardInterrupt:
                print("\nStopped.")
                return
            except AppError as exc:
                print(f"Error: {exc}")
            except Exception as exc:
                print(f"Error: {exc}")
            time.sleep(poll_interval_seconds(config))
        return

    if args.command == "bot":
        from bot import run_bot

        run_bot()
        return


if __name__ == "__main__":
    main()
