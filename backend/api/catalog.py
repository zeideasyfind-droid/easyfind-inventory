"""Catalog API routes — manual Meta Commerce Catalog sync.

POST /catalog/sync-all   — reads every row from the Google Sheet and
                           pushes them to Meta Catalog in one batch call.
POST /catalog/sync       — body: {"property_id": "..."}
                           syncs a single row looked up from the sheet.

These endpoints are for manual / scheduled triggering.  Per-extract
auto-sync runs as a FastAPI BackgroundTask inside /extract.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services import google_sheets
from backend.services.google_sheets import GoogleSheetsError
from backend.services.meta_catalog_service import (
    MetaCatalogAuthError,
    MetaCatalogError,
    MetaCatalogRateLimitError,
    upsert_batch,
    upsert_item,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/catalog", tags=["catalog"])


class SyncOneRequest(BaseModel):
    property_id: str


@router.post("/sync")
async def sync_one(payload: SyncOneRequest):
    """Sync a single property (by property_id) from the sheet to Meta Catalog."""
    property_id = (payload.property_id or "").strip()
    if not property_id:
        raise HTTPException(status_code=400, detail="property_id is required.")

    try:
        rows = google_sheets.get_existing_rows()
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    row = next(
        (r for r in rows if r.get("property_id") == property_id),
        None,
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No row found with property_id={property_id!r}.",
        )

    try:
        result = await upsert_item(row)
    except MetaCatalogAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except MetaCatalogRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except MetaCatalogError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "status": "synced",
        "property_id": property_id,
        "meta_response": result,
    }


@router.post("/sync-all")
async def sync_all():
    """Read every row from the Google Sheet and push them to Meta Catalog.

    Rows without a ``property_id`` are skipped (they can't be addressed in
    the catalog).  Returns a summary with counts and any handles Meta returned.
    """
    try:
        rows = google_sheets.get_existing_rows()
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Filter to rows that have a property_id (column X).
    valid = [r for r in rows if r.get("property_id")]
    skipped = len(rows) - len(valid)

    if not valid:
        return {
            "status": "nothing_to_sync",
            "total_rows": len(rows),
            "skipped_no_id": skipped,
        }

    items = [{"normalized": row} for row in valid]

    try:
        result = await upsert_batch(items)
    except MetaCatalogAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except MetaCatalogRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except MetaCatalogError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info(
        "sync-all complete — synced=%d skipped=%d handles=%s",
        len(valid),
        skipped,
        result.get("handles"),
    )
    return {
        "status": "synced",
        "synced": len(valid),
        "skipped_no_id": skipped,
        "meta_response": result,
    }
