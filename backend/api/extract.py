from fastapi import APIRouter, HTTPException

from backend.models.property import ExtractRequest
from backend.services import contact_extractor, duplicate_checker, firecrawl, google_drive, google_sheets
from backend.services.firecrawl import FirecrawlError
from backend.services.google_sheets import GoogleSheetsError
from backend.services.normalizer import normalize_property
from backend.utils import detect_portal, generate_property_id, utc_now_iso

router = APIRouter()


@router.post("/extract")
async def extract(payload: ExtractRequest):
    # The exact string the user pasted is the canonical URL end-to-end:
    # it is what gets written to Google Sheets (column W), never a
    # redirect/auth/intermediate/Firecrawl-resolved URL a portal like
    # MyGate might send the scraper through.
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="A property URL is required.")

    # 1. Firecrawl scrapes the page and its built-in LLM returns structured
    # JSON, plus the raw markdown/html for the contact-number rescue below.
    try:
        scrape_result = await firecrawl.extract_property(url)
    except FirecrawlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    raw = scrape_result["fields"]

    # 2. Normalize the extracted fields into the exact sheet column values.
    normalized = normalize_property(raw)
    normalized["url"] = url
    normalized["portal"] = detect_portal(url)
    normalized["property_id"] = generate_property_id()
    normalized["extracted_at"] = utc_now_iso()

    # 2b. Contact number rescue: the schema-based extraction alone can
    # miss or mask a contact number that's fully visible elsewhere on the
    # page. Re-search the raw extraction plus markdown/html/rawHtml for a
    # complete, unmasked Indian mobile number. Never infers/reconstructs
    # partial numbers -- if nothing valid is found anywhere, the contact
    # field is left empty rather than guessed.
    normalized["contact_number"] = contact_extractor.find_indian_mobile(
        raw.get("contact_number"),
        normalized.get("contact_number"),
        scrape_result.get("markdown"),
        scrape_result.get("html"),
        scrape_result.get("rawHtml"),
    )

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
