from fastapi import APIRouter, HTTPException

from backend.services import google_sheets
from backend.services.google_sheets import GoogleSheetsError

router = APIRouter()


@router.get("/inventory")
async def inventory():
    """Return everything currently stored in the Google Sheet worksheet,
    for convenience (not part of the original spec)."""
    try:
        rows = google_sheets.get_existing_rows()
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"count": len(rows), "items": rows}
