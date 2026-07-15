"""WhatsApp Cloud API delivery (11_WHATSAPP_DELIVERY_ENGINE.md, extended
in the Phase 4 migration to support mixed image/video albums).

Uploads each media file directly to WhatsApp's own Media API (no
third-party CDN), then sends one message per upload in original order --
images as `type: image`, videos as `type: video` -- attaching the
EasyFind caption to only the first message. The Cloud API has no native
"media album" grouping call, so this is the closest equivalent: one
outbound group of messages, one caption.

A previous internal project's WhatsApp integration was reviewed as a
migration reference (auth/config/logging conventions only -- see
replit.md "Module 2 WhatsApp migration" for what was and wasn't
reused). That project sent outbound images via Cloudinary-hosted public
links and had no outbound video support or retry logic at all; both are
deliberately NOT carried over here, per product decision, in favor of
keeping direct Media API uploads as the single source of truth and
adding the retry/video support the spec actually requires.

Never logs the access token.
"""
import asyncio
import logging

import httpx

from backend.config import settings
from backend.services.validation_service import media_kind

logger = logging.getLogger("backend.whatsapp")

GRAPH_BASE = "https://graph.facebook.com/v20.0"
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0


class WhatsAppError(Exception):
    pass


async def _with_retries(description: str, coro_fn, *args):
    """Retries transient (network / 5xx) failures with exponential
    backoff (1s, 2s, 4s...). 4xx failures are not retried -- they won't
    succeed on repetition (bad token, unsupported media, etc.)."""
    last_exc = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await coro_fn(*args)
        except WhatsAppError as exc:
            last_exc = exc
            status = getattr(exc, "status_code", 0)
            if status and status < 500:
                logger.error("%s failed (non-retryable, status=%s): %s", description, status, exc)
                raise
            logger.warning("%s failed (attempt %d/%d, status=%s): %s", description, attempt, _MAX_ATTEMPTS, status, exc)
        except httpx.HTTPError as exc:
            last_exc = WhatsAppError(str(exc))
            logger.warning("%s network error (attempt %d/%d): %s", description, attempt, _MAX_ATTEMPTS, exc)
        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    logger.error("%s failed after %d attempts", description, _MAX_ATTEMPTS)
    raise last_exc


async def send_media_album(media_files: list[tuple[str, bytes, str]], caption: str) -> dict:
    """media_files: list of (filename, content_bytes, content_type) preserving
    the original upload order -- images and videos may be freely mixed.
    Returns {"message_id", "image_count"} (image_count = total media sent,
    kept for API-response backward compatibility)."""
    access_token = settings.WHATSAPP_ACCESS_TOKEN
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    recipient = settings.WHATSAPP_RECIPIENT_NUMBER

    if not access_token or not phone_number_id or not recipient:
        raise WhatsAppError("WhatsApp Cloud API is not configured.")

    async with httpx.AsyncClient(timeout=60) as client:
        uploads = []  # [(media_id, kind), ...] in original order
        for filename, content, content_type in media_files:
            kind = media_kind(content_type)
            media_id = await _with_retries(
                f"media upload ({filename})",
                _upload_media,
                client,
                phone_number_id,
                access_token,
                filename,
                content,
                content_type,
            )
            uploads.append((media_id, kind))
            logger.info("Uploaded %s to WhatsApp Media API (%s)", filename, kind)

        first_message_id = None
        for index, (media_id, kind) in enumerate(uploads):
            message_id = await _with_retries(
                f"send message #{index + 1} ({kind})",
                _send_media_message,
                client,
                phone_number_id,
                access_token,
                recipient,
                media_id,
                kind,
                caption if index == 0 else None,
            )
            if index == 0:
                first_message_id = message_id
            logger.info("Sent %s message %d/%d (id=%s)", kind, index + 1, len(uploads), message_id)

    return {"message_id": first_message_id, "image_count": len(uploads)}


async def _upload_media(client, phone_number_id, access_token, filename, content, content_type):
    response = await client.post(
        f"{GRAPH_BASE}/{phone_number_id}/media",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"messaging_product": "whatsapp"},
        files={"file": (filename, content, content_type)},
    )
    body = response.json() if response.content else {}
    if response.status_code >= 400 or "id" not in body:
        detail = (body.get("error") or {}).get("message") or body
        error = WhatsAppError(f"WhatsApp media upload failed for {filename}: {detail}")
        error.status_code = response.status_code
        raise error
    return body["id"]


async def _send_media_message(client, phone_number_id, access_token, recipient, media_id, kind, caption):
    media_payload = {"id": media_id}
    if caption:
        media_payload["caption"] = caption

    response = await client.post(
        f"{GRAPH_BASE}/{phone_number_id}/messages",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": kind,
            kind: media_payload,
        },
    )
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        detail = (body.get("error") or {}).get("message") or body
        error = WhatsAppError(f"WhatsApp send failed: {detail}")
        error.status_code = response.status_code
        raise error

    messages = body.get("messages") or []
    return messages[0]["id"] if messages else None
