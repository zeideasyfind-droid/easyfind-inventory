"""Syncs property listings to Meta Commerce Catalog via the Graph API.

Endpoint: POST https://graph.facebook.com/v18.0/{catalog_id}/batch

Each property maps to a Meta real-estate/retail product item.  The batch
call uses method=UPDATE so that pushing an existing ``retailer_id`` is an
upsert (no duplicates in the catalog).

Error handling:
  - 401/403  → MetaCatalogAuthError (token or permission problem)
  - 429      → MetaCatalogRateLimitError (caller should back off and retry)
  - other 4xx/5xx → MetaCatalogError
"""
import logging
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.facebook.com/v18.0"
_TIMEOUT = 30


class MetaCatalogError(Exception):
    pass


class MetaCatalogAuthError(MetaCatalogError):
    pass


class MetaCatalogRateLimitError(MetaCatalogError):
    pass


# ---------------------------------------------------------------- helpers --


def _build_title(normalized: dict) -> str:
    bhk = normalized.get("bhk_label") or ""
    location = normalized.get("property_location") or ""
    society = normalized.get("society_name") or ""

    if bhk and society:
        return f"{bhk} in {society}"
    if bhk and location:
        return f"{bhk} Apartment in {location}"
    if society:
        return society
    if location:
        return f"Rental property in {location}"
    return "Rental Property"


def _build_description(normalized: dict) -> str:
    parts: list[str] = []

    bhk = normalized.get("bhk_label")
    area = normalized.get("area_label")
    furnishing = normalized.get("furnishing")
    floor = normalized.get("floor_label")
    society = normalized.get("society_name")
    location = normalized.get("property_location")
    rent = normalized.get("rent")
    deposit = normalized.get("deposit")
    available = normalized.get("available_from")
    tenant = normalized.get("tenant_preference")
    portal = normalized.get("portal")

    if bhk:
        parts.append(bhk)
    if area:
        parts.append(area)
    if furnishing:
        parts.append(furnishing)
    if floor:
        parts.append(f"Floor {floor}")
    if society:
        parts.append(society)
    if location:
        parts.append(location)
    if rent:
        parts.append(f"Rent ₹{int(rent):,}/month")
    if deposit:
        parts.append(f"Deposit ₹{int(deposit):,}")
    if available:
        parts.append(f"Available from {available}")
    if tenant:
        parts.append(f"Preferred: {tenant}")
    if portal:
        parts.append(f"Source: {portal}")

    return " | ".join(parts) if parts else "Residential rental listing."


def build_catalog_item(
    normalized: dict,
    image_url: str = "",
) -> dict[str, Any]:
    """Build the Meta catalog product dict from a normalized property row."""
    property_id = normalized.get("property_id") or ""
    rent = normalized.get("rent")
    listing_url = normalized.get("url") or ""

    # Meta requires price as an integer in the smallest currency unit.
    # For INR, the smallest unit is paise (1 INR = 100 paise).
    price_paise = int(float(rent) * 100) if rent else 0

    item: dict[str, Any] = {
        "id": property_id,
        "title": _build_title(normalized),
        "description": _build_description(normalized),
        "availability": "in stock",
        "condition": "new",
        "price": price_paise,
        "currency": "INR",
        "link": listing_url,
    }
    if image_url:
        item["image_link"] = image_url

    return item


def _check_response(response: httpx.Response) -> None:
    status = response.status_code
    if status == 200:
        return
    if status in (401, 403):
        raise MetaCatalogAuthError(
            f"Meta Graph API auth failure ({status}). "
            "Check WHATSAPP_TOKEN has 'catalog_management' permission."
        )
    if status == 429:
        raise MetaCatalogRateLimitError(
            "Meta Graph API rate limit hit (429). Back off before retrying."
        )
    raise MetaCatalogError(
        f"Meta Graph API error ({status}): {response.text[:500]}"
    )


# ---------------------------------------------------------------- public API -


async def upsert_item(
    normalized: dict,
    image_url: str = "",
) -> dict:
    """Push a single property to the Meta Commerce Catalog.

    Uses the batch endpoint with method=UPDATE (upsert semantics — an
    existing ``retailer_id`` is overwritten, not duplicated).

    Returns the Graph API response body.
    """
    catalog_id = settings.META_CATALOG_ID
    token = settings.WHATSAPP_ACCESS_TOKEN
    if not catalog_id:
        raise MetaCatalogError("META_CATALOG_ID is not configured.")
    if not token:
        raise MetaCatalogAuthError("WHATSAPP_TOKEN / WHATSAPP_ACCESS_TOKEN is not configured.")

    item = build_catalog_item(normalized, image_url)
    property_id = item["id"]
    if not property_id:
        raise MetaCatalogError("Cannot sync a property without a property_id.")

    payload = {
        "requests": [
            {
                "method": "UPDATE",
                "retailer_id": property_id,
                "data": item,
            }
        ],
        "access_token": token,
    }

    url = f"{_GRAPH_BASE}/{catalog_id}/batch"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(url, json=payload)

    _check_response(response)
    body = response.json()

    # Log any per-item errors Meta reports inside a 200 response.
    handles = body.get("handles") or []
    logger.info(
        "Meta Catalog upsert OK — property_id=%s handles=%s",
        property_id,
        handles,
    )
    return body


async def upsert_batch(items: list[dict]) -> dict:
    """Push multiple catalog items in one Graph API batch call (max 1000).

    Each element of *items* is a dict with keys ``normalized`` and
    optionally ``image_url``.

    Returns the Graph API response body.
    """
    catalog_id = settings.META_CATALOG_ID
    token = settings.WHATSAPP_ACCESS_TOKEN
    if not catalog_id:
        raise MetaCatalogError("META_CATALOG_ID is not configured.")
    if not token:
        raise MetaCatalogAuthError("WHATSAPP_TOKEN / WHATSAPP_ACCESS_TOKEN is not configured.")

    requests_payload = []
    for entry in items:
        normalized = entry.get("normalized", {})
        image_url = entry.get("image_url", "")
        item = build_catalog_item(normalized, image_url)
        pid = item.get("id")
        if not pid:
            logger.warning("Skipping item with no property_id in batch sync.")
            continue
        requests_payload.append({
            "method": "UPDATE",
            "retailer_id": pid,
            "data": item,
        })

    if not requests_payload:
        return {"handles": [], "skipped": "no valid items"}

    payload = {
        "requests": requests_payload,
        "access_token": token,
    }

    url = f"{_GRAPH_BASE}/{catalog_id}/batch"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(url, json=payload)

    _check_response(response)
    body = response.json()
    logger.info(
        "Meta Catalog batch upsert OK — %d items, handles=%s",
        len(requests_payload),
        body.get("handles"),
    )
    return body
