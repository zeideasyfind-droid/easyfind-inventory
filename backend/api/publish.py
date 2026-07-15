"""Module 2 API endpoints (12_API_SPECIFICATION.md).

POST /publish/preview - parse + enrich + format, return the caption only.
POST /publish/send     - same pipeline, then deliver via WhatsApp Cloud API.
GET  /publish/status  - configuration diagnostics: which env vars are present.
                        Never exposes secret values -- only boolean 'present'
                        per variable plus a masked preview of phone IDs.

The frontend never talks to Google Maps or WhatsApp directly -- only these
endpoints, and all upstream credentials stay server-side.
"""
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.config import settings
from backend.models.publish import (
    PublishPreviewResponse,
    PublishSendResponse,
    WhatsAppStatusResponse,
    WhatsAppStatusVar,
)
from backend.services import community_service, formatter_service, maps_service, parser_service
from backend.services.validation_service import ValidationError, validate_publish_request
from backend.services.whatsapp_service import GRAPH_BASE, WhatsAppError, send_media_album
from backend.utils import generate_request_id, mask_phone

router = APIRouter(prefix="/publish")


@router.get("/status", response_model=WhatsAppStatusResponse)
async def publish_status():
    """Diagnostic endpoint: returns which WhatsApp env vars are configured.

    Use this to confirm whether 'WhatsApp Cloud API is not configured.'
    is caused by missing secrets before attempting a real send.
    Token is NEVER returned -- only a boolean 'present' is exposed.
    Phone number ID and recipient are masked (first 4 + last 2 chars).
    """
    token = settings.WHATSAPP_ACCESS_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    recipient = settings.WHATSAPP_RECIPIENT_NUMBER
    maps_key = settings.GOOGLE_MAPS_API_KEY

    return WhatsAppStatusResponse(
        configured=bool(token and phone_id and recipient),
        graph_base=GRAPH_BASE,
        access_token=WhatsAppStatusVar(
            present=bool(token),
            masked_value=None,  # access token value is never exposed
        ),
        phone_number_id=WhatsAppStatusVar(
            present=bool(phone_id),
            masked_value=mask_phone(phone_id) if phone_id else None,
        ),
        recipient_number=WhatsAppStatusVar(
            present=bool(recipient),
            masked_value=mask_phone(recipient) if recipient else None,
        ),
        maps_api_key_present=bool(maps_key),
    )


async def _run_pipeline(owner_message: str, images: List[UploadFile]):
    validate_publish_request(owner_message, images)

    parsed = parser_service.parse_owner_message(owner_message)

    place = None
    maps_url = parsed.get("maps_url")
    if maps_url:
        # A Maps lookup failure must never break the publish flow -- fall
        # back to whatever the owner's own message already said (parsed
        # owner_community/owner_society) and keep the original URL, per
        # 14_ERROR_HANDLING.md / 08_GOOGLE_MAPS_ENRICHMENT.md.
        try:
            place = await maps_service.enrich_from_maps_url(maps_url, parsed.get("maps_place_hint"))
        except Exception:
            place = None

    community_info = community_service.classify_community(place, parsed)
    listing = formatter_service.build_listing(parsed, community_info, maps_url)
    return parsed, community_info, listing


@router.post("/preview", response_model=PublishPreviewResponse)
async def publish_preview(
    owner_message: str = Form(""),
    images: List[UploadFile] = File(default_factory=list),
):
    try:
        parsed, community_info, listing = await _run_pipeline(owner_message, images)
    except ValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return PublishPreviewResponse(
        success=True,
        preview=listing,
        community=community_info.get("community", "Unknown"),
        society=community_info.get("society"),
        landmark=community_info.get("landmark"),
        maps_url=parsed.get("maps_url"),
    )


@router.post("/send", response_model=PublishSendResponse)
async def publish_send(
    owner_message: str = Form(""),
    images: List[UploadFile] = File(default_factory=list),
):
    request_id = generate_request_id()

    try:
        parsed, community_info, listing = await _run_pipeline(owner_message, images)
    except ValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    media_payloads = []
    for image in images:
        content = await image.read()
        media_payloads.append((image.filename or "media", content, image.content_type or "application/octet-stream"))

    try:
        result = await send_media_album(media_payloads, listing)
    except WhatsAppError as exc:
        # Never lose the generated caption on a delivery failure -- return
        # it so the broker can copy it manually and retry without having
        # to reformat, per 11_WHATSAPP_DELIVERY_ENGINE.md / 14_ERROR_HANDLING.md.
        return PublishSendResponse(
            success=False,
            image_count=len(media_payloads),
            delivery="failed",
            preview=listing,
            error=str(exc),
            request_id=request_id,
        )

    return PublishSendResponse(
        success=True,
        message_id=result.get("message_id"),
        image_count=result.get("image_count", len(media_payloads)),
        delivery="sent",
        request_id=request_id,
    )
