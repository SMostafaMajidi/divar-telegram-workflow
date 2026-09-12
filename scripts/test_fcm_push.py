#!/usr/bin/env python3
"""Manual / dry-run FCM push tester.

Examples:
  FCM_DRY_RUN=1 python scripts/test_fcm_push.py --token SAMPLE_TOKEN
  python scripts/test_fcm_push.py --token REAL_FCM_TOKEN --title "تست" --body "سلام"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test FCM notification")
    parser.add_argument("--token", required=True, help="FCM registration token")
    parser.add_argument("--title", default="آگهی جدید · تست")
    parser.add_argument("--body", default="نوتیف تست از بک‌اند workflow")
    parser.add_argument("--dry-run", action="store_true", help="Force FCM_DRY_RUN=1")
    parser.add_argument("--filter-id", default="test-filter")
    parser.add_argument("--listing-token", default="abc123")
    parser.add_argument("--url", default="https://divar.ir/v/a/abc123")
    args = parser.parse_args()

    if args.dry_run:
        os.environ["FCM_DRY_RUN"] = "1"

    from fcm import fcm_configured, fcm_mode, mask_fcm_token, send_data_message

    print("mode:", fcm_mode())
    print("configured:", fcm_configured())
    print("token:", mask_fcm_token(args.token))
    result = send_data_message(
        args.token,
        title=args.title,
        body=args.body,
        data={
            "type": "listing",
            "filter_id": args.filter_id,
            "token": args.listing_token,
            "url": args.url,
            "title": args.title,
            "price": "توافقی",
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") or result.get("skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
