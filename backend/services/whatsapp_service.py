"""WhatsApp Cloud API delivery (11_WHATSAPP_DELIVERY_ENGINE.md).

Uploads each image, then sends one image message per upload in original
order, attaching the EasyFind caption to only the first image -- the Cloud
API has no native "media album" grouping call, so this is the closest
equivalent: one outbound group of messages, one caption. Access tokens
never leave the backend.
"""
import asyncio

import httpx

from backend.config import settings

GRAPH_BASE = "https://graph.facebook.com/v20.0"
_MAX_ATTEMPTS = 3


class WhatsAppError(Exception):
    pass


async def _with_retries(coro_fn, *args):
    """Retries transient (network / 5xx) failures per
    11_WHATSAPP_DELIVERY_ENGINE.md ("Retry transient API failures").
    Does not retry 4xx errors -- those are not transient."""
    last_exc = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await coro_fn(*args)
        except WhatsAppError as exc:
            last_exc = exc
            if getattr(exc, "status_code", 0) and exc.status_code < 500:
                raise
        except httpx.HTTPError as exc:
            last_exc = WhatsAppError(str(exc))
        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(0.5 * attempt)
    raise last_exc


async def send_media_album(images: list[tuple[str, bytes, str]], caption: str) -> dict:
    """images: list of (filename, content_bytes, content_type) preserving
    the original upload order. Returns {"message_id", "image_count"}."""
    access_token = settings.WHATSAPP_ACCESS_TOKEN
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    recipient = settings.WHATSAPP_RECIPIENT_NUMBER

    if not access_token or not phone_number_id or not recipient:
        raise WhatsAppError("WhatsApp Cloud API is not configured.")

    async with httpx.AsyncClient(timeout=60) as client:
        media_ids = []
        for filename, content, content_type in images:
            media_id = await _with_retries(
                _upload_media, client, phone_number_id, access_token, filename, content, content_type
            )
            media_ids.append(media_id)

        first_message_id = None
        for index, media_id in enumerate(media_ids):
            message_id = await _with_retries(
                _send_image_message,
                client,
                phone_number_id,
                access_token,
                recipient,
                media_id,
                caption if index == 0 else None,
            )
            if index == 0:
                first_message_id = message_id

    return {"message_id": first_message_id, "image_count": len(media_ids)}


async def _upload_media(client, phone_number_id, access_token, filename, content, content_type):
    response = await client.post(
        f"{GRAPH_BASE}/{phone_number_id}/media",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"messaging_product": "whatsapp"},
        files={"file": (filename, content, content_type)},
    )
    body = response.json() if response.content else {}
    if response.status_code >= 400 or "id" not in body:
        error = WhatsAppError(f"WhatsApp media upload failed for {filename}: {body}")
        error.status_code = response.status_code
        raise error
    return body["id"]


async def _send_image_message(client, phone_number_id, access_token, recipient, media_id, caption):
    image_payload = {"id": media_id}
    if caption:
        image_payload["caption"] = caption

    response = await client.post(
        f"{GRAPH_BASE}/{phone_number_id}/messages",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "image",
            "image": image_payload,
        },
    )
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        error = WhatsAppError(f"WhatsApp send failed: {body}")
        error.status_code = response.status_code
        raise error

    messages = body.get("messages") or []
    return messages[0]["id"] if messages else None
