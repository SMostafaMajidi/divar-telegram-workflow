from __future__ import annotations

import argparse

import db
from config_store import AppError, detect_telegram_chat, load_config, load_dotenv
from notifier import TelegramNotifier
from runner import build_notifier, send_best_for_user


def main() -> None:
    load_dotenv()
    db.init_db()
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
        users = [u for u in db.list_users() if u.get("active") and u.get("ai_enabled")]
        if not users:
            raise SystemExit("No active users with AI enabled.")
        for user in users:
            try:
                result = send_best_for_user(user)
                print(f"@{user['telegram_username']}: {result['message']}")
            except AppError as exc:
                print(f"@{user['telegram_username']}: {exc}")
        return

    if args.command == "watch":
        from config_store import format_slot_time, next_due_watch_users
        from runner import watch_tick
        import time
        import db as database

        print("watching per-user clock slots")
        include_now = True
        while True:
            users = [bundle["user"] for bundle in database.active_users_with_filters()]
            due, wait, when = next_due_watch_users(users, include_now=include_now)
            include_now = False
            if wait > 0:
                print(f"next scan at {format_slot_time(when)} ({len(due)} user(s) queued)")
                try:
                    time.sleep(wait)
                except KeyboardInterrupt:
                    print("\nStopped.")
                    return
                users = [bundle["user"] for bundle in database.active_users_with_filters()]
                due, _, when = next_due_watch_users(users, include_now=True)
            try:
                result = watch_tick(user_ids=[user["id"] for user in due] if due else [])
                print(result["message"])
            except KeyboardInterrupt:
                print("\nStopped.")
                return
            except AppError as exc:
                print(f"Error: {exc}")
            except Exception as exc:
                print(f"Error: {exc}")
        return

    if args.command == "bot":
        from bot import run_bot

        run_bot()
        return


if __name__ == "__main__":
    main()
