from fastapi import APIRouter, HTTPException

from backend.models.property import ExtractRequest
from backend.services import duplicate_checker, firecrawl, google_drive, google_sheets
from backend.services.firecrawl import FirecrawlError
from backend.services.google_sheets import GoogleSheetsError
from backend.services.normalizer import normalize_property
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

    # 2. Normalize the extracted fields.
    normalized = normalize_property(raw)
    normalized["portal_url"] = url
    normalized["property_id"] = generate_property_id()
    normalized["extracted_at"] = utc_now_iso()

    # 3. Duplicate check against what's already in the sheet.
    try:
        existing_rows = google_sheets.get_existing_rows()
    except GoogleSheetsError:
        existing_rows = []

    duplicate = duplicate_checker.find_duplicate(normalized, existing_rows)
    if duplicate:
        return {
            "status": "duplicate",
            "message": "This property already exists in the inventory.",
            "matched_property_id": duplicate.get("property_id"),
        }

    # 4. Archive the JSON before writing to Sheets (never skipped).
    google_drive.archive_property(normalized)

    # 5. Append the inventory row to Google Sheets.
    try:
        sheet_row = google_sheets.append_row(normalized)
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "status": "success",
        "property_id": normalized["property_id"],
        "sheet_row": sheet_row,
    }
