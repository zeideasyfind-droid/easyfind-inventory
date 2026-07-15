"""Module 2 API endpoints (12_API_SPECIFICATION.md).

POST /publish/preview - parse + enrich + format, return the caption only.
POST /publish/send     - same pipeline, then deliver via WhatsApp Cloud API.

The frontend never talks to Google Maps or WhatsApp directly -- only these
two endpoints, and all upstream credentials stay server-side.
"""
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.models.publish import PublishPreviewResponse, PublishSendResponse
from backend.services import community_service, formatter_service, maps_service, parser_service
from backend.services.validation_service import ValidationError, validate_publish_request
from backend.services.whatsapp_service import WhatsAppError, send_media_album

router = APIRouter(prefix="/publish")


async def _run_pipeline(owner_message: str, images: List[UploadFile]):
    validate_publish_request(owner_message, images)

    parsed = parser_service.parse_owner_message(owner_message)

    place = None
    maps_url = parsed.get("maps_url")
    if maps_url:
        # A Maps lookup failure must never break the publish flow -- fall
        # back to Community: Unknown and keep the original URL, per
        # 14_ERROR_HANDLING.md.
        try:
            place = await maps_service.enrich_from_maps_url(maps_url)
        except Exception:
            place = None

    community_info = community_service.classify_community(place)
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
        )

    return PublishSendResponse(
        success=True,
        message_id=result.get("message_id"),
        image_count=result.get("image_count", len(media_payloads)),
        delivery="sent",
    )
