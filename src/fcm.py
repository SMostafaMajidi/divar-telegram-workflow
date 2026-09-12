from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from config_store import ROOT, AppError, load_config, load_dotenv
from divar import Listing

log = logging.getLogger("fcm")

LEGACY_FCM_URL = "https://fcm.googleapis.com/fcm/send"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

_access_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


def mask_fcm_token(token: str) -> str:
    raw = str(token or "").strip()
    if not raw:
        return ""
    if len(raw) <= 10:
        return "••••" + raw[-2:]
    return raw[:4] + "…" + raw[-4:]


def fcm_dry_run() -> bool:
    load_dotenv()
    return str(os.getenv("FCM_DRY_RUN") or "").strip().lower() in {"1", "true", "yes", "on"}


def fcm_service_account_path() -> Path | None:
    load_dotenv()
    raw = (
        os.getenv("FCM_SERVICE_ACCOUNT_FILE")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        or ""
    ).strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path if path.is_file() else None


def fcm_project_id() -> str:
    load_dotenv()
    explicit = (os.getenv("FCM_PROJECT_ID") or "").strip()
    if explicit:
        return explicit
    path = fcm_service_account_path()
    if not path:
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("project_id") or "").strip()


def fcm_server_key() -> str:
    load_dotenv()
    return (os.getenv("FCM_SERVER_KEY") or "").strip()


def fcm_configured() -> bool:
    if fcm_dry_run():
        return True
    if fcm_server_key():
        return True
    path = fcm_service_account_path()
    return bool(path and fcm_project_id())


def fcm_mode() -> str:
    if fcm_dry_run():
        return "dry_run"
    if fcm_service_account_path() and fcm_project_id():
        return "http_v1"
    if fcm_server_key():
        return "legacy"
    return "off"


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_rs256(message: bytes, private_key_pem: str) -> bytes:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        pass
    else:
        key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
        return key.sign(message, padding.PKCS1v15(), hashes.SHA256())

    try:
        from google.auth.crypt import RSASigner

        signer = RSASigner.from_string(private_key_pem)
        return signer.sign(message)
    except Exception:
        pass

    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as tmp:
        tmp.write(private_key_pem)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", tmp_path],
            input=message,
            capture_output=True,
            check=True,
        )
        return proc.stdout
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass


def _service_account_access_token() -> str:
    now = time.time()
    cached = str(_access_token_cache.get("token") or "")
    expires_at = float(_access_token_cache.get("expires_at") or 0)
    if cached and now < expires_at - 60:
        return cached

    path = fcm_service_account_path()
    if not path:
        raise AppError("FCM service account file is missing.")
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AppError("FCM service account JSON invalid.") from exc

    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(
            info, scopes=[FCM_SCOPE]
        )
        creds.refresh(Request())
        token = str(creds.token or "")
        _access_token_cache["token"] = token
        _access_token_cache["expires_at"] = now + 3300
        return token
    except ImportError:
        pass
    except Exception as exc:
        log.warning("google-auth refresh failed, falling back to JWT: %s", exc)

    client_email = str(info.get("client_email") or "").strip()
    private_key = str(info.get("private_key") or "")
    if not client_email or not private_key:
        raise AppError("FCM service account missing client_email/private_key.")

    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claim = {
        "iss": client_email,
        "scope": FCM_SCOPE,
        "aud": OAUTH_TOKEN_URL,
        "iat": int(now),
        "exp": int(now) + 3600,
    }
    payload = _b64url(json.dumps(claim, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64url(_sign_rs256(signing_input, private_key))
    assertion = f"{header}.{payload}.{signature}"

    response = requests.post(
        OAUTH_TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    token = str(data.get("access_token") or "")
    if not token:
        raise AppError("FCM OAuth token empty.")
    expires_in = int(data.get("expires_in") or 3600)
    _access_token_cache["token"] = token
    _access_token_cache["expires_at"] = now + max(60, expires_in)
    return token


def _is_invalid_token_error(status_code: int, body: dict[str, Any] | str) -> bool:
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    upper = text.upper()
    if "UNREGISTERED" in upper or "NOTREGISTERED" in upper:
        return True
    if "NOT_FOUND" in upper or "NOTFOUND" in upper:
        return True
    if ("INVALIDREGISTRATION" in upper or "MISMATCHEDSENDERID" in upper):
        return True
    if "REGISTRATION-TOKEN-NOT-REGISTERED" in upper:
        return True
    if isinstance(body, dict):
        results = body.get("results")
        if isinstance(results, list) and results:
            err = str((results[0] or {}).get("error") or "").upper()
            if err in {"NOTREGISTERED", "INVALIDREGISTRATION", "MISMATCHEDSENDERID"}:
                return True
        error = body.get("error")
        if isinstance(error, dict):
            details = error.get("details") or []
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                err_code = str(detail.get("errorCode") or "").upper()
                if err_code in {"UNREGISTERED", "INVALID_ARGUMENT"}:
                    # INVALID_ARGUMENT only when token-ish
                    msg = str(error.get("message") or "").upper()
                    if err_code == "UNREGISTERED" or "TOKEN" in msg:
                        return True
    if status_code == 404:
        return True
    return False


def send_data_message(
    token: str,
    *,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Send one FCM message. Never raises for network/API errors — returns status dict."""
    device = str(token or "").strip()
    if not device:
        return {"ok": False, "invalid_token": False, "error": "empty token", "skipped": True}

    mode = fcm_mode()
    payload_data = {str(k): str(v) for k, v in (data or {}).items()}
    masked = mask_fcm_token(device)

    if mode == "off":
        log.info("FCM skip (not configured) token=%s", masked)
        return {"ok": False, "invalid_token": False, "error": "fcm_not_configured", "skipped": True}

    if mode == "dry_run":
        log.info(
            "FCM dry-run title=%r body=%r token=%s data_keys=%s",
            title,
            body,
            masked,
            sorted(payload_data.keys()),
        )
        return {"ok": True, "invalid_token": False, "error": "", "dry_run": True}

    try:
        if mode == "http_v1":
            return _send_http_v1(device, title=title, body=body, data=payload_data)
        return _send_legacy(device, title=title, body=body, data=payload_data)
    except Exception as exc:
        log.warning("FCM send failed token=%s err=%s", masked, exc)
        return {"ok": False, "invalid_token": False, "error": str(exc)}


def _send_http_v1(
    token: str,
    *,
    title: str,
    body: str,
    data: dict[str, str],
) -> dict[str, Any]:
    project_id = fcm_project_id()
    access = _service_account_access_token()
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    message = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": data,
            "android": {
                "priority": "HIGH",
                "notification": {
                    "channel_id": "listings",
                    "default_sound": True,
                    "default_vibrate_timings": True,
                },
            },
        }
    }
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json=message,
        timeout=25,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}
    if response.ok:
        return {"ok": True, "invalid_token": False, "error": "", "response": payload}
    invalid = _is_invalid_token_error(
        response.status_code, payload if isinstance(payload, dict) else str(payload)
    )
    err = ""
    if isinstance(payload, dict):
        err = str(
            ((payload.get("error") or {}).get("message"))
            or payload.get("error")
            or response.text[:300]
        )
    else:
        err = str(payload)[:300]
    return {
        "ok": False,
        "invalid_token": invalid,
        "error": err or f"HTTP {response.status_code}",
    }


def _send_legacy(
    token: str,
    *,
    title: str,
    body: str,
    data: dict[str, str],
) -> dict[str, Any]:
    key = fcm_server_key()
    message = {
        "to": token,
        "priority": "high",
        "notification": {"title": title, "body": body, "sound": "default"},
        "data": data,
    }
    response = requests.post(
        LEGACY_FCM_URL,
        headers={
            "Authorization": f"key={key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json=message,
        timeout=25,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}
    if response.ok and isinstance(payload, dict) and int(payload.get("success") or 0) > 0:
        return {"ok": True, "invalid_token": False, "error": "", "response": payload}
    invalid = _is_invalid_token_error(
        response.status_code, payload if isinstance(payload, dict) else str(payload)
    )
    err = ""
    if isinstance(payload, dict):
        results = payload.get("results") or []
        if results and isinstance(results[0], dict):
            err = str(results[0].get("error") or "")
        err = err or str(payload.get("error") or response.text[:300])
    else:
        err = str(payload)[:300]
    return {
        "ok": False,
        "invalid_token": invalid,
        "error": err or f"HTTP {response.status_code}",
    }


def push_fresh_listings(
    user_id: str,
    *,
    filter_id: str,
    filter_name: str,
    listings: list[Listing],
    devices: list[dict[str, Any]] | None = None,
    max_send: int | None = None,
) -> dict[str, Any]:
    """Push new listings to all enabled devices for a user. Safe if FCM is off."""
    import db

    if not listings:
        return {"sent": 0, "failed": 0, "devices": 0, "skipped": True}

    devices = devices if devices is not None else db.list_enabled_device_tokens(user_id)
    if not devices:
        return {"sent": 0, "failed": 0, "devices": 0, "skipped": True}

    config = load_config()
    limit = max_send
    if limit is None:
        limit = int(config.get("max_send_per_run") or config.get("best_count") or 5)
    limit = max(1, min(int(limit), 25))

    to_send = list(listings[:limit])
    remaining = len(listings) - len(to_send)
    sent = 0
    failed = 0
    last_error = ""

    if not fcm_configured():
        log.info(
            "FCM not configured; skip push user=%s filter=%s listings=%s devices=%s",
            user_id,
            filter_id,
            len(listings),
            len(devices),
        )
        db.log_watch_event(
            user_id,
            action="deliver",
            status="skipped",
            filter_id=filter_id,
            filter_name=filter_name,
            platform="divar",
            channel="app",
            found_count=len(listings),
            new_count=len(listings),
            sent_count=0,
            destination=f"devices:{len(devices)}",
            message="FCM تنظیم نشده؛ push رد شد.",
        )
        return {"sent": 0, "failed": 0, "devices": len(devices), "skipped": True}

    for item in to_send:
        title = f"آگهی جدید · {filter_name}"
        body = f"{item.title} — {item.price}".strip(" —")
        data = {
            "type": "listing",
            "filter_id": str(filter_id or ""),
            "token": str(item.token or ""),
            "url": str(item.url or ""),
            "title": str(item.title or ""),
            "price": str(item.price or ""),
        }
        for device in devices:
            tok = str(device.get("token") or "")
            result = send_data_message(tok, title=title, body=body, data=data)
            if result.get("ok"):
                sent += 1
            else:
                failed += 1
                last_error = str(result.get("error") or last_error)
                if result.get("invalid_token"):
                    db.delete_device_token_by_value(tok)
                    log.info("Removed invalid FCM token %s", mask_fcm_token(tok))

    if remaining > 0 and devices:
        title = f"آگهی جدید · {filter_name}"
        body = f"{len(listings)} آگهی جدید برای فیلتر {filter_name}"
        data = {
            "type": "listing_batch",
            "filter_id": str(filter_id or ""),
            "count": str(len(listings)),
            "title": body,
            "price": "",
            "token": "",
            "url": "",
        }
        for device in devices:
            tok = str(device.get("token") or "")
            result = send_data_message(tok, title=title, body=body, data=data)
            if result.get("ok"):
                sent += 1
            else:
                failed += 1
                last_error = str(result.get("error") or last_error)
                if result.get("invalid_token"):
                    db.delete_device_token_by_value(tok)

    if failed and not sent:
        status = "failure"
        message = f"push ناموفق ({failed}): {last_error}"
    elif failed:
        status = "partial"
        message = f"push جزئی: {sent} موفق · {failed} ناموفق"
    else:
        status = "success"
        message = f"push موفق: {sent} پیام به {len(devices)} دستگاه"

    db.log_watch_event(
        user_id,
        action="deliver",
        status=status,
        filter_id=filter_id,
        filter_name=filter_name,
        platform="divar",
        channel="app",
        found_count=len(listings),
        new_count=len(listings),
        sent_count=sent,
        destination=f"devices:{len(devices)}",
        message=message,
        detail=(
            {"failed": failed, "error": last_error, "mode": fcm_mode()}
            if failed
            else {"mode": fcm_mode()}
        ),
    )
    return {
        "sent": sent,
        "failed": failed,
        "devices": len(devices),
        "listings": len(to_send),
        "mode": fcm_mode(),
    }
