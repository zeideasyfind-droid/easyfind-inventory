"""Google Maps enrichment (08_GOOGLE_MAPS_ENRICHMENT.md).

Resolves the owner-pasted Maps URL -- including shortened
maps.app.goo.gl / goo.gl/maps links -- then calls the Google Places API to
identify what was pinned. community_service uses the result to classify
Gated / Semi-Gated / Standalone.

Failure handling: any network/API error here must never abort the publish
flow. Callers get None back and continue formatting with
Community: Unknown while preserving the original Maps URL, per
14_ERROR_HANDLING.md.
"""
import httpx

from backend.config import settings
from backend.services.parser_service import extract_place_hint

FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


async def _resolve_redirect(url: str) -> str:
    """Shortened Maps links redirect to the full maps.google.com URL that
    actually carries the place name/coordinates."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url)
        return str(response.url)
    except httpx.HTTPError:
        return url


async def _find_named_place(client: httpx.AsyncClient, api_key: str, place_name: str, coords):
    """Looks up an explicitly named place (the owner shared a Maps pin for
    a specific society/building) -- this is the only path that can yield
    Gated/Semi-Gated, since it is the only case where we actually know a
    building name rather than just a raw location."""
    params = {
        "input": place_name,
        "inputtype": "textquery",
        "fields": "name,formatted_address,types,geometry",
        "key": api_key,
    }
    if coords:
        params["locationbias"] = f"point:{coords[0]},{coords[1]}"

    response = await client.get(FIND_PLACE_URL, params=params)
    body = response.json()
    candidates = body.get("candidates") or []
    if not candidates:
        return None

    candidate = candidates[0]
    return {
        "source": "named",
        "name": candidate.get("name"),
        "formatted_address": candidate.get("formatted_address"),
        "types": candidate.get("types") or [],
        "location": (candidate.get("geometry") or {}).get("location"),
    }


async def _nearest_landmark(client: httpx.AsyncClient, api_key: str, coords):
    """The owner only dropped a raw pin (no place name) -- there is no
    known society, so find the nearest public landmark for a Standalone
    listing rather than guessing a building name."""
    params = {
        "location": f"{coords[0]},{coords[1]}",
        "rankby": "distance",
        "type": "point_of_interest",
        "key": api_key,
    }
    response = await client.get(NEARBY_SEARCH_URL, params=params)
    body = response.json()
    results = body.get("results") or []
    if not results:
        return None

    result = results[0]
    return {
        "source": "nearby",
        "name": result.get("name"),
        "formatted_address": result.get("vicinity"),
        "types": result.get("types") or [],
        "location": (result.get("geometry") or {}).get("location"),
    }


async def enrich_from_maps_url(maps_url: str) -> dict | None:
    """Returns a dict with name/types/source, or None if enrichment could
    not be completed at all (caller continues with Community: Unknown)."""
    api_key = settings.GOOGLE_MAPS_API_KEY
    if not api_key or not maps_url:
        return None

    resolved_url = await _resolve_redirect(maps_url)
    place_name, coords = extract_place_hint(resolved_url)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if place_name:
                named = await _find_named_place(client, api_key, place_name, coords)
                if named:
                    return named
            if coords:
                return await _nearest_landmark(client, api_key, coords)
    except httpx.HTTPError:
        return None

    return None
