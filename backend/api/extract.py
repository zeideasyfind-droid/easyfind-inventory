from fastapi import APIRouter, HTTPException

from backend.models.property import ExtractRequest
from backend.services import duplicate_checker, firecrawl, google_drive, google_sheets
from backend.services.firecrawl import FirecrawlError
from backend.services.google_sheets import GoogleSheetsError
from backend.services.normalizer import detect_portal, normalize_property
from backend.utils import generate_property_id, utc_now_iso

router = APIRouter()


@router.post("/extract")
async def extract(payload: ExtractRequest):
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="A property URL is required.")

    # 1. Firecrawl scrapes the page and its built-in LLM returns structured JSON.
    try:
        raw = await firecrawl.extract_property(url)
    except FirecrawlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # 2. Normalize the extracted fields into the exact sheet column values.
    normalized = normalize_property(raw)
    normalized["url"] = url
    normalized["portal"] = detect_portal(url)
    normalized["property_id"] = generate_property_id()
    normalized["extracted_at"] = utc_now_iso()

    # 3. Check whether this listing already has a row (by URL, else by
    # Contact Number + Society Name + Rent) so we upsert instead of
    # creating a duplicate.
    try:
        existing_rows = google_sheets.get_existing_rows()
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    matched_row = duplicate_checker.find_matching_row(normalized, existing_rows)

    # 4. Archive the JSON before writing to Sheets (never skipped).
    google_drive.archive_property(normalized)

    # 5. Insert or update the inventory row in Google Sheets.
    try:
        sheet_row, action = google_sheets.upsert_row(normalized, matched_row)
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "status": "success",
        "action": action,
        "property_id": normalized["property_id"],
        "sheet_row": sheet_row,
    }
