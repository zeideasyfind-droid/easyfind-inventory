"""Google Maps enrichment — EasyFind inventory pipeline.

Resolves the owner-pasted Maps URL (including shortened maps.app.goo.gl /
goo.gl/maps links), fetches full Place Details from the Google Places API,
and returns enough structured metadata for community_service to make a
confident Gated / Semi-Gated / Standalone classification.

Classification strategy (priority order)
-----------------------------------------
1. Google Place Details types (authoritative, API-provided).
2. Place name keyword heuristics (secondary signal only).
3. Fallback to nearest landmark ONLY when Google returns nothing useful
   — never Standalone by default / parser failure.

Place type → community mapping
-------------------------------
Gated Community  → types contain any of:
    residential_complex, housing_complex, gated_community,
    real_estate_agency  (when name has gated keywords)
Semi Gated       → types contain any of:
    premise, subpremise, apartment_complex, apartment_building,
    establishment  (when name looks like a standalone building)
Standalone       → raw pin / no named place found / types match
    point_of_interest only

Failure handling
----------------
Any network / API error must never abort the publish flow.
Callers receive None and continue with Community: Unknown while
preserving the original Maps URL.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

import httpx

from backend.config import settings

# ── Google Places API endpoints ──────────────────────────────────────────────────

FIND_PLACE_URL   = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

# ── Type sets used for classification ─────────────────────────────────────────────

# Types that Google applies to large residential societies / complexes.
_GATED_TYPES = {
    "residential_complex",
    "housing_complex",
    "gated_community",
    "neighborhood",
}

# Types that indicate a specific named building (smaller, semi-gated).
_BUILDING_TYPES = {
    "premise",
    "subpremise",
    "establishment",
    "apartment_complex",
    "apartment_building",
    "lodging",
}

# Name keywords that override building classification → Gated Community.
_GATED_NAME_KEYWORDS = (
    "township", "layout", "enclave", "county",
    "meadows", "gardens", "habitat", "city", "nagar",
    "phase", "greens", "woods", "palm", "royale",
    "elite", "eco ", "society", "residences",
)

# ── URL helpers ───────────────────────────────────────────────────────────────────

_COORD_RE = re.compile(r"[@/](-?\d+\.\d+),(-?\d+\.\d+)")


async def _resolve_redirect(url: str) -> str:
    """Follow redirects on shortened Maps URLs to obtain the canonical URL."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url)
        return str(response.url)
    except httpx.HTTPError:
        return url


def _extract_place_name_from_url(url: str) -> str | None:
    """Extract a human-readable place name encoded in a Maps URL path,
    e.g. /maps/place/Odion+The+Woods+of+East/@... → 'Odion The Woods of East'.
    """
    try:
        path = unquote(urlparse(url).path)
        match = re.search(r"/place/([^/@]+)", path)
        if match:
            name = match.group(1).replace("+", " ").strip()
            if name:
                return name
    except Exception:
        pass
    return None


def _extract_coords_from_url(url: str) -> tuple[float, float] | None:
    """Extract latitude/longitude from a Maps URL."""
    match = _COORD_RE.search(url)
    if match:
        try:
            return float(match.group(1)), float(match.group(2))
        except ValueError:
            pass
    return None


def _locality_from_address_components(components: list[dict]) -> str | None:
    """Extract the locality (neighbourhood/sublocality/locality) from
    Google's address_components array.  Prefer the most specific level."""
    priority = [
        "sublocality_level_1",
        "sublocality",
        "neighborhood",
        "locality",
    ]
    component_map: dict[str, str] = {}
    for comp in components or []:
        for t in comp.get("types") or []:
            if t not in component_map:
                component_map[t] = comp.get("long_name", "")
    for p in priority:
        if p in component_map and component_map[p]:
            return component_map[p]
    return None


# ── API calls ────────────────────────────────────────────────────────────────────

async def _get_place_details(
    client: httpx.AsyncClient,
    api_key: str,
    place_name: str,
    coords: tuple[float, float] | None,
) -> dict | None:
    """Find a place by name and fetch its full Place Details (types +
    address_components).  Returns None if nothing is found.

    Two-step:
      1. FindPlace  → place_id
      2. Place Details → types, name, address_components
    """
    # Step 1: find the place_id.
    find_params: dict = {
        "input": place_name,
        "inputtype": "textquery",
        "fields": "place_id,name,types,geometry",
        "key": api_key,
    }
    if coords:
        find_params["locationbias"] = f"point:{coords[0]},{coords[1]}"

    find_resp = await client.get(FIND_PLACE_URL, params=find_params)
    find_body = find_resp.json()
    candidates = find_body.get("candidates") or []
    if not candidates:
        return None

    candidate = candidates[0]
    place_id = candidate.get("place_id")
    if not place_id:
        return None

    # Step 2: fetch rich details with types + address_components.
    details_params: dict = {
        "place_id": place_id,
        "fields": "name,types,address_components,geometry",
        "key": api_key,
    }
    det_resp = await client.get(PLACE_DETAILS_URL, params=details_params)
    det_body = det_resp.json()
    result = det_body.get("result")
    if not result:
        # Fall back to candidate data from FindPlace.
        return {
            "source": "find_place",
            "name": candidate.get("name"),
            "types": candidate.get("types") or [],
            "address_components": [],
            "location": (candidate.get("geometry") or {}).get("location"),
        }

    return {
        "source": "place_details",
        "name": result.get("name"),
        "types": result.get("types") or [],
        "address_components": result.get("address_components") or [],
        "location": (result.get("geometry") or {}).get("location"),
    }


async def _nearest_landmark(
    client: httpx.AsyncClient,
    api_key: str,
    coords: tuple[float, float],
) -> dict | None:
    """Fall back to nearest public POI when no named place was found.
    This is the ONLY path that should produce community=Standalone.
    """
    params = {
        "location": f"{coords[0]},{coords[1]}",
        "rankby": "distance",
        "type": "point_of_interest",
        "key": api_key,
    }
    resp = await client.get(NEARBY_SEARCH_URL, params=params)
    body = resp.json()
    results = body.get("results") or []
    if not results:
        return None
    result = results[0]
    return {
        "source": "nearby",
        "name": result.get("name"),
        "types": result.get("types") or [],
        "address_components": [],
        "location": (result.get("geometry") or {}).get("location"),
    }


# ── Classification (local, mirrors community_service logic) ────────────────────

def _classify_place(place: dict) -> str:
    """Return 'Gated Community', 'Semi Gated', or 'Standalone'.

    Priority:
      1. Google types (authoritative).
      2. Name keyword heuristics.
      3. Source fallback.
    """
    if place.get("source") == "nearby":
        return "Standalone"

    types = set(place.get("types") or [])
    name  = (place.get("name") or "").lower()

    # Hard Gated signals from Google
    if types & _GATED_TYPES:
        return "Gated Community"

    # Building type + name keyword → could be either
    if types & _BUILDING_TYPES:
        if any(kw in name for kw in _GATED_NAME_KEYWORDS):
            return "Gated Community"
        return "Semi Gated"

    # Name-only keyword heuristic when Google types are generic
    if any(kw in name for kw in _GATED_NAME_KEYWORDS):
        return "Gated Community"
    if any(kw in name for kw in ("apartment", "residency", "heights", "towers", "block")):
        return "Semi Gated"

    # If Google returned a named place but types are unhelpful,
    # default to Semi Gated (never Standalone from a named place).
    if place.get("name"):
        return "Semi Gated"

    return "Standalone"


# ── Public API ───────────────────────────────────────────────────────────────────

async def enrich_from_maps_url(
    maps_url: str,
    text_place_hint: str | None = None,
) -> dict | None:
    """Enrich a Maps URL with full Place Details.

    Returns a dict with:
      source       : 'place_details' | 'find_place' | 'nearby' | 'hint'
      name         : canonical place name from Google
      types        : list[str]  — raw Google place types
      community    : 'Gated Community' | 'Semi Gated' | 'Standalone'
      locality     : str | None  — neighbourhood/locality from address_components
      address_components : list[dict]

    Returns None only on total failure (network / missing API key).
    Callers fall back to Community: Unknown and preserve the original URL.

    Classification guarantees
    -------------------------
    • community=Standalone is ONLY set when Google’s source is 'nearby'
      (bare pin, no named place at all) or when types contain exclusively
      point_of_interest-level signals.
    • A named place returned by FindPlace / Place Details is NEVER
      classified Standalone merely because the parser had no text hint.
    """
    api_key = settings.GOOGLE_MAPS_API_KEY
    if not api_key or not maps_url:
        return None

    # 1. Resolve shortened URL to canonical Maps URL.
    resolved_url = await _resolve_redirect(maps_url)

    # 2. Extract name and coords from the resolved URL path.
    place_name = _extract_place_name_from_url(resolved_url)
    coords     = _extract_coords_from_url(resolved_url)

    # 3. If URL had no name, try the text hint from the owner message.
    if not place_name and text_place_hint:
        place_name = text_place_hint.strip() or None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            place: dict | None = None

            if place_name:
                place = await _get_place_details(client, api_key, place_name, coords)

            if not place and coords:
                # No named place found — fall back to nearest landmark.
                # This is the ONLY legitimate Standalone path.
                place = await _nearest_landmark(client, api_key, coords)

            if not place:
                return None

            locality = _locality_from_address_components(
                place.get("address_components") or []
            )

            return {
                "source"            : place["source"],
                "name"              : place.get("name"),
                "types"             : place.get("types") or [],
                "community"         : _classify_place(place),
                "locality"          : locality,
                "address_components": place.get("address_components") or [],
            }

    except httpx.HTTPError:
        return None
