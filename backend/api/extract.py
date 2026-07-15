from fastapi import APIRouter, HTTPException

from backend.models.property import ExtractRequest
from backend.services import duplicate_checker, firecrawl, google_drive, google_sheets
from backend.services.firecrawl import FirecrawlError
from backend.services.google_sheets import GoogleSheetsError
from backend.services.normalizer import normalize_property
from backend.utils import detect_portal, generate_property_id, utc_now_iso

router = APIRouter()


@router.post("/extract")
async def extract(payload: ExtractRequest):
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

    matched_row = duplicate_checker.find_matching_row(normalized, existing_rows)

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
        raise HTTPException(status_code=502, detail=f"Archiving failed after sheet write: {exc}") from exc

    return {
        "status": "success",
        "action": action,
        "property_id": property_id,
        "sheet_row": sheet_row,
    }
