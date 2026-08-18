from __future__ import annotations

import argparse
import sys
import time

from config_store import AppError, detect_telegram_chat, load_config, load_dotenv, poll_interval_seconds
from notifier import TelegramNotifier
from runner import build_notifier, run_filters


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Search Divar and send listings to Telegram")
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve", "once", "watch", "test", "chat-id"],
        help="serve web UI, once one scan, watch loop, test telegram, chat-id detect",
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
        _run_cli(args.dry_run)
        return

    interval = poll_interval_seconds(config)
    print(f"watching every {interval // 60} min")
    while True:
        try:
            _run_cli(args.dry_run)
        except KeyboardInterrupt:
            print("\nStopped.")
            sys.exit(0)
        except AppError as exc:
            print(f"Error: {exc}")
        except Exception as exc:
            print(f"Error: {exc}")
        time.sleep(interval)


def _run_cli(dry_run: bool) -> None:
    try:
        result = run_filters(dry_run=dry_run)
    except AppError as exc:
        raise SystemExit(str(exc)) from exc
    print(result["message"])
    if dry_run:
        for item in result.get("listings") or []:
            print("-" * 40)
            print(item.get("title"))
            print(item.get("price"), item.get("location"))
            print(item.get("url"))


if __name__ == "__main__":
    main()
