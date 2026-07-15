import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend.models.property import ExtractRequest
from backend.services import duplicate_checker, firecrawl, google_drive, google_sheets
from backend.services.cloudinary_service import CloudinaryError, extract_og_image, upload_and_transform
from backend.services.firecrawl import FirecrawlError
from backend.services.google_sheets import GoogleSheetsError
from backend.services.meta_catalog_service import MetaCatalogError, upsert_item
from backend.services.normalizer import normalize_property
from backend.utils import detect_portal, generate_property_id, utc_now_iso

logger = logging.getLogger(__name__)
router = APIRouter()


async def _sync_to_catalog(normalized: dict, image_url: str) -> None:
    """Background task: upload image to Cloudinary then push to Meta Catalog.

    Failures are logged but never surfaced to the caller — catalog sync
    must not block or roll back a successful sheet write.
    """
    cloudinary_url = ""
    if image_url:
        try:
            cloudinary_url = await upload_and_transform(image_url)
        except CloudinaryError as exc:
            logger.warning(
                "Cloudinary upload failed for property_id=%s: %s",
                normalized.get("property_id"),
                exc,
            )

    try:
        await upsert_item(normalized, image_url=cloudinary_url)
    except MetaCatalogError as exc:
        logger.warning(
            "Meta Catalog sync failed for property_id=%s: %s",
            normalized.get("property_id"),
            exc,
        )


@router.post("/extract")
async def extract(payload: ExtractRequest, background_tasks: BackgroundTasks):
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="A property URL is required.")

    try:
        scrape_result = await firecrawl.extract_property(url)
    except FirecrawlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    raw = scrape_result["fields"]
    normalized = normalize_property(raw)
    normalized["url"] = url
    normalized["portal"] = detect_portal(url)
    normalized["extracted_at"] = utc_now_iso()

    try:
        existing_rows = google_sheets.get_existing_rows()
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    match_result = duplicate_checker.find_best_match(normalized, existing_rows)
    matched_row = match_result.row
    normalized["property_fingerprint"] = match_result.fingerprint

    property_id = (
        matched_row.get("property_id")
        if matched_row and matched_row.get("property_id")
        else generate_property_id()
    )
    normalized["property_id"] = property_id

    sheet_write_timestamp = utc_now_iso()
    try:
        sheet_row, action = google_sheets.upsert_row(normalized, matched_row)
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    archive_metadata = {
        "property_id": property_id,
        "original_url": url,
        "portal": normalized["portal"],
        "extraction_timestamp_utc": normalized["extracted_at"],
        "archive_timestamp_utc": utc_now_iso(),
        "firecrawl_model_or_version": firecrawl.extract_firecrawl_model(scrape_result),
        "application_version": google_drive.detect_application_version(),
        "archive_status": "completed",
        "sheet_write_timestamp": sheet_write_timestamp,
        "archive_timestamp": utc_now_iso(),
    }

    try:
        google_drive.archive_property(
            property_id=property_id,
            normalized=normalized,
            firecrawl_response=scrape_result["raw_response"],
            markdown=scrape_result.get("markdown", ""),
            metadata=archive_metadata,
        )
    except Exception as exc:
        archive_metadata["archive_status"] = "archive_failed"
        archive_metadata["archive_timestamp"] = utc_now_iso()
        raise HTTPException(
            status_code=502,
            detail=f"Archiving failed after sheet write: {exc}",
        ) from exc

    # Kick off Cloudinary upload + Meta Catalog sync in the background.
    # This never blocks the response and never rolls back the sheet write.
    og_image = extract_og_image(scrape_result["raw_response"])
    background_tasks.add_task(_sync_to_catalog, normalized.copy(), og_image or "")

    return {
        "status": "success",
        "action": action,
        "property_id": property_id,
        "sheet_row": sheet_row,
    }
