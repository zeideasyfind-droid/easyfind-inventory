"""WhatsApp Cloud API delivery with full outbound observability.

Every send request:
  1. Verifies the Phone Number ID resolves to the registered business
     number before uploading any media -- aborts with PhoneNumberMismatchError
     if the display_phone_number returned by the Graph API does not match
     the configured recipient number.
  2. Logs every Graph API call in structured detail: request ID, recipient,
     phone number ID, last-6 of access token, exact endpoint, full request
     payload (token excluded), HTTP status, full response body, message IDs,
     contacts, error codes, and fbtrace_id.
  3. Treats success only when messages[0].id is present in the Graph
     response -- HTTP 200 with an empty messages[] is still an error.

Never logs the access token in full. Only the last 6 characters are logged
for correlation with Meta's own logs.
"""
import asyncio
import json
import logging
import re

import httpx

from backend.config import settings
from backend.services.validation_service import media_kind

logger = logging.getLogger("backend.whatsapp")

GRAPH_BASE = "https://graph.facebook.com/v20.0"
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0

# The registered business number this deployment is allowed to send from.
# Any mismatch between this and Graph's display_phone_number aborts the send.
EXPECTED_DISPLAY_NUMBER = "+91 70269 49566"


class WhatsAppError(Exception):
    pass


class PhoneNumberMismatchError(WhatsAppError):
    """Raised when the Phone Number ID resolves to a different number than
    the one registered for this deployment."""
    pass


def _token_tail(token: str) -> str:
    """Last 6 characters of the access token -- safe for logging."""
    return ("..." + token[-6:]) if token and len(token) >= 6 else "[short]"


def _normalise_phone(number: str) -> str:
    """Strip spaces and normalise to digits + leading + for comparison.
    '+91 70269 49566' and '+917026949566' are treated as equal."""
    return re.sub(r"\s+", "", number or "")


def _log_graph_response(request_id: str, description: str, endpoint: str,
                        payload: dict | None, status: int, body: dict) -> None:
    """Emit one structured log line covering the full Graph interaction."""
    error = body.get("error") or {}
    logger.info(
        "[%s] Graph call | %s | endpoint=%s | http_status=%s | "
        "messages=%s | contacts=%s | "
        "error_code=%s | error_subcode=%s | fbtrace_id=%s | "
        "payload=%s | full_body=%s",
        request_id,
        description,
        endpoint,
        status,
        json.dumps(body.get("messages") or []),
        json.dumps(body.get("contacts") or []),
        error.get("code"),
        error.get("error_subcode"),
        error.get("fbtrace_id"),
        json.dumps(payload) if payload is not None else "<multipart>",
        json.dumps(body),
    )


async def verify_phone_number(client: httpx.AsyncClient,
                              phone_number_id: str,
                              access_token: str,
                              request_id: str) -> dict:
    """GET /{phone_number_id} -- confirms the ID resolves to the expected
    registered business number before any media is uploaded.

    Returns the full Graph response dict.
    Raises PhoneNumberMismatchError if display_phone_number does not match.
    Raises WhatsAppError on API/network failure.
    """
    endpoint = f"{GRAPH_BASE}/{phone_number_id}"
    params = {
        "fields": "id,display_phone_number,verified_name,quality_rating,status,"
                  "whatsapp_business_account_id",
        "access_token": access_token,  # sent as query param, NOT logged
    }
    try:
        response = await client.get(endpoint, params=params)
    except httpx.HTTPError as exc:
        raise WhatsAppError(f"Phone number verification network error: {exc}") from exc

    body = response.json() if response.content else {}

    # Log without the token -- params logged without access_token value.
    safe_params = {k: v for k, v in params.items() if k != "access_token"}
    logger.info(
        "[%s] Phone number verification | endpoint=%s | http_status=%s | "
        "id=%s | display_phone_number=%s | verified_name=%s | "
        "quality_rating=%s | status=%s | whatsapp_business_account_id=%s | "
        "token_tail=%s | full_body=%s",
        request_id,
        endpoint,
        response.status_code,
        body.get("id"),
        body.get("display_phone_number"),
        body.get("verified_name"),
        body.get("quality_rating"),
        body.get("status"),
        body.get("whatsapp_business_account_id"),
        _token_tail(access_token),
        json.dumps(body),
    )

    if response.status_code >= 400:
        error = (body.get("error") or {})
        raise WhatsAppError(
            f"Phone number ID lookup failed (HTTP {response.status_code}): "
            f"{error.get('message') or body}"
        )

    display = body.get("display_phone_number") or ""
    if _normalise_phone(display) != _normalise_phone(EXPECTED_DISPLAY_NUMBER):
        raise PhoneNumberMismatchError(
            f"Phone number mismatch: Graph API returned '{display}' for "
            f"WHATSAPP_PHONE_NUMBER_ID={phone_number_id!r} but the registered "
            f"business number for this deployment is "
            f"'{EXPECTED_DISPLAY_NUMBER}'. Send aborted."
        )

    return body


async def _with_retries(description: str, coro_fn, *args):
    """Retries transient (network / 5xx) failures with exponential
    backoff (1s, 2s, 4s...). 4xx failures are not retried."""
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
            logger.warning("%s failed (attempt %d/%d, status=%s): %s",
                           description, attempt, _MAX_ATTEMPTS, status, exc)
        except httpx.HTTPError as exc:
            last_exc = WhatsAppError(str(exc))
            logger.warning("%s network error (attempt %d/%d): %s",
                           description, attempt, _MAX_ATTEMPTS, exc)
        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    logger.error("%s failed after %d attempts", description, _MAX_ATTEMPTS)
    raise last_exc


async def send_media_album(
    media_files: list[tuple[str, bytes, str]],
    caption: str,
    request_id: str = "",
) -> dict:
    """Uploads each file to WhatsApp Media API then sends one message per
    file in original order, caption on first only.

    Steps:
      0. Config guard -- fail fast if any required env var is missing.
      1. Pre-send phone number verification -- abort on mismatch.
      2. Upload each file, logging full request/response.
      3. Send each message, logging full request/response.
      4. Validate success by checking messages[0].id in Graph response.

    Returns {"message_id", "image_count"}.
    """
    access_token = settings.WHATSAPP_ACCESS_TOKEN
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    recipient = settings.WHATSAPP_RECIPIENT_NUMBER

    if not access_token or not phone_number_id or not recipient:
        raise WhatsAppError("WhatsApp Cloud API is not configured.")

    logger.info(
        "[%s] send_media_album START | recipient=%s | phone_number_id=%s | "
        "token_tail=%s | file_count=%d",
        request_id, recipient, phone_number_id,
        _token_tail(access_token), len(media_files),
    )

    async with httpx.AsyncClient(timeout=60) as client:

        # ----------------------------------------------------------------
        # Step 1 -- pre-send phone number verification
        # ----------------------------------------------------------------
        await verify_phone_number(client, phone_number_id, access_token, request_id)

        # ----------------------------------------------------------------
        # Step 2 -- upload all media
        # ----------------------------------------------------------------
        uploads = []  # [(media_id, kind), ...] in original order
        for filename, content, content_type in media_files:
            kind = media_kind(content_type)
            media_id = await _with_retries(
                f"[{request_id}] media upload ({filename})",
                _upload_media,
                client, phone_number_id, access_token,
                filename, content, content_type, request_id,
            )
            uploads.append((media_id, kind))
            logger.info("[%s] Uploaded %s (%s) -> media_id=%s",
                        request_id, filename, kind, media_id)

        # ----------------------------------------------------------------
        # Step 3 & 4 -- send messages, validate response
        # ----------------------------------------------------------------
        first_message_id = None
        for index, (media_id, kind) in enumerate(uploads):
            message_id = await _with_retries(
                f"[{request_id}] send message #{index + 1} ({kind})",
                _send_media_message,
                client, phone_number_id, access_token, recipient,
                media_id, kind,
                caption if index == 0 else None,
                request_id,
            )
            if index == 0:
                first_message_id = message_id
            logger.info(
                "[%s] Message %d/%d sent | kind=%s | message_id=%s",
                request_id, index + 1, len(uploads), kind, message_id,
            )

    logger.info(
        "[%s] send_media_album COMPLETE | first_message_id=%s | total=%d | "
        "Meta Messaging Insights: https://business.facebook.com/wa/manage/phone-numbers/",
        request_id, first_message_id, len(uploads),
    )
    return {"message_id": first_message_id, "image_count": len(uploads)}


async def _upload_media(
    client, phone_number_id, access_token,
    filename, content, content_type, request_id,
):
    endpoint = f"{GRAPH_BASE}/{phone_number_id}/media"
    payload_desc = {"messaging_product": "whatsapp", "file": filename,
                    "content_type": content_type}

    response = await client.post(
        endpoint,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"messaging_product": "whatsapp"},
        files={"file": (filename, content, content_type)},
    )
    body = response.json() if response.content else {}

    _log_graph_response(request_id, f"media upload ({filename})",
                        endpoint, payload_desc, response.status_code, body)

    if response.status_code >= 400 or "id" not in body:
        detail = (body.get("error") or {}).get("message") or body
        error = WhatsAppError(f"WhatsApp media upload failed for {filename}: {detail}")
        error.status_code = response.status_code
        raise error
    return body["id"]


async def _send_media_message(
    client, phone_number_id, access_token, recipient,
    media_id, kind, caption, request_id,
):
    endpoint = f"{GRAPH_BASE}/{phone_number_id}/messages"
    media_payload = {"id": media_id}
    if caption:
        media_payload["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": kind,
        kind: media_payload,
    }

    response = await client.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    body = response.json() if response.content else {}

    _log_graph_response(request_id, f"send {kind} message",
                        endpoint, payload, response.status_code, body)

    if response.status_code >= 400:
        error = (body.get("error") or {})
        exc = WhatsAppError(
            f"WhatsApp send failed (HTTP {response.status_code}): "
            f"{error.get('message') or body}"
        )
        exc.status_code = response.status_code
        raise exc

    # Validated success: HTTP 200 alone is not sufficient.
    messages = body.get("messages") or []
    if not messages or not messages[0].get("id"):
        exc = WhatsAppError(
            f"Graph API returned HTTP {response.status_code} but messages[] "
            f"is missing or empty -- cannot confirm delivery. "
            f"Full response: {json.dumps(body)}"
        )
        exc.status_code = response.status_code
        raise exc

    return messages[0]["id"]
