"""Deterministic, rule-based parser for a raw owner property message.

Never uses an LLM and never invents values -- every field returned here is
either lifted directly from the pasted text via regex, or left as None so
the formatter can omit it. This is stage 1 of the formatter pipeline
described in 07_FORMATTER_ENGINE.md (Raw Message -> Parser -> Standardizer).
"""
import re
from urllib.parse import unquote, unquote_plus

from backend.services.normalizer import (
    area_label,
    bhk_label,
    normalize_available_from,
    normalize_bhk_number,
    normalize_furnishing,
    normalize_money,
)
from backend.utils import extract_number

_MAPS_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:maps\.app\.goo\.gl|goo\.gl/maps|maps\.google\.[a-z.]+|"
    r"google\.[a-z.]+/maps)\S*",
    re.IGNORECASE,
)

_BHK_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[- ]?\s*bhk", re.IGNORECASE)

# ── Money regexes — capture raw owner text (87k / 2.5L / 25000) ──────────────
# Group 1: the raw amount string exactly as the owner wrote it.
_RENT_RAW_RE = re.compile(
    r"\brent\b[^\n\d]{0,20}?(\d[\d,\.]*\s*(?:k|l|lakh|lakhs)?)", re.IGNORECASE
)
_DEPOSIT_RAW_RE = re.compile(
    r"\bdeposit\b[^\n\d]{0,20}?(\d[\d,\.]*\s*(?:k|l|lakh|lakhs)?)", re.IGNORECASE
)

# Maintenance: may be a number/shorthand OR a plain-text phrase like
# "Water bill", "Included in rent", "Maintenance included", "NA".
# Two regexes: value-first and label-first.
_MAINTENANCE_VALUE_RE = re.compile(
    r"\bmaintenance\b[:\- \t]*([^\n]{1,50})", re.IGNORECASE
)
_MAINTENANCE_INCLUDED_RE = re.compile(r"maintenance\s+included", re.IGNORECASE)
_MAINTENANCE_KEYWORD_RE  = re.compile(r"maintenance", re.IGNORECASE)

_AREA_RE = re.compile(r"([\d,\.]+)\s*(?:sq\.?\s*ft\.?|sqft|sft)", re.IGNORECASE)

_BATHROOM_LABEL_RE = re.compile(r"(?:bathroom|toilet|washroom)s?[:\-]?[ \t]*(\d+)", re.IGNORECASE)
_BATHROOM_NUM_RE   = re.compile(r"(\d+)[ \t]*(?:bathroom|toilet|washroom)s?", re.IGNORECASE)
_BALCONY_LABEL_RE  = re.compile(r"balcon\w*[:\-]?[ \t]*(\d+)", re.IGNORECASE)
_BALCONY_NUM_RE    = re.compile(r"(\d+)[ \t]*balcon", re.IGNORECASE)

_AVAILABLE_RE = re.compile(r"available(?:\s*from)?[:\-]?\s*([^\n,]+)", re.IGNORECASE)

# ── Floor ─────────────────────────────────────────────────────────────────────
# Matches patterns like:
#   Floor: 3rd floor      Floor: G+2        Floor: 2 Story Villa
#   3rd Floor             Ground Floor      2nd floor / 10 total
_FLOOR_LABEL_RE = re.compile(r"\bfloor\b[:\- \t]+([^\n]{1,40})", re.IGNORECASE)
_FLOOR_NUM_RE   = re.compile(r"(\d+(?:st|nd|rd|th)?\s*(?:floor|storey|story))", re.IGNORECASE)
_FLOOR_STORY_RE = re.compile(r"(\d+\s*story\s+(?:villa|house|bungalow|duplex|independent))", re.IGNORECASE)
_FLOOR_G_RE     = re.compile(r"\b(G\+\d+)\b", re.IGNORECASE)
_FLOOR_GROUND_RE = re.compile(r"\b(ground\s*floor)\b", re.IGNORECASE)

# ── Tenant preference ─────────────────────────────────────────────────────────
_TENANT_LABEL_RE = re.compile(
    r"(?:preferred\s*)?tenant[:\- \t]+([^\n]{1,40})", re.IGNORECASE
)
_TENANT_PREF_RE  = re.compile(
    r"(?:preferred\s*)?tenant[s]?\s+(?:preferred|preference)[:\-]?\s*([^\n]{1,40})",
    re.IGNORECASE,
)

# ── Pets ──────────────────────────────────────────────────────────────────────
_PETS_LABEL_RE = re.compile(r"\bpets?\b[:\- \t]+([^\n]{1,30})", re.IGNORECASE)
_PETS_ALLOWED_RE     = re.compile(r"\bpets?\s+allowed\b", re.IGNORECASE)
_PETS_NOT_ALLOWED_RE = re.compile(r"\bpets?\s+not\s+allowed\b|\bno\s+pets?\b", re.IGNORECASE)

# ── Location ──────────────────────────────────────────────────────────────────
# Owner messages often say "Location: Sarjapur Road" or "Located in HSR Layout".
_LOCATION_LABEL_RE = re.compile(
    r"\blocation[:\- \t]+([^\n]{1,60})", re.IGNORECASE
)
_LOCATED_IN_RE = re.compile(
    r"\blocated\s+(?:in|at|near)\s+([^\n,]{1,60})", re.IGNORECASE
)

_BROKERAGE_APPLICABLE_RE     = re.compile(r"brokerage\s+applicable", re.IGNORECASE)
_BROKERAGE_NOT_APPLICABLE_RE = re.compile(
    r"no\s+brokerage|brokerage\s*[-:]?\s*(?:not\s+applicable|nil|none)", re.IGNORECASE
)

_FURNISHING_KEYWORDS = (
    "fully furnished",
    "full furnished",
    "semi-furnished",
    "semi furnished",
    "unfurnished",
    "un-furnished",
    "furnished",
)

_COMMUNITY_LABEL_RE = re.compile(r"\bcommunity\b[:\-]?\s*([^\n]+)", re.IGNORECASE)
_SOCIETY_LABEL_RE   = re.compile(
    r"\b(?:society|apartment|complex|building)\s*(?:name)?[:\-]\s*([^\n]+)", re.IGNORECASE
)
_SEMI_GATED_HINTS  = ("semi-gated", "semi gated")
_GATED_HINTS       = ("gated",)
_STANDALONE_HINTS  = ("standalone", "stand-alone", "independent")


def _normalize_owner_community(label_text: str | None) -> str | None:
    if not label_text:
        return None
    lowered = label_text.lower()
    if any(hint in lowered for hint in _SEMI_GATED_HINTS):
        return "Semi-Gated"
    if any(hint in lowered for hint in _GATED_HINTS):
        return "Gated"
    if any(hint in lowered for hint in _STANDALONE_HINTS):
        return "Standalone"
    return None


def detect_maps_url(text: str) -> str | None:
    """Scan the pasted owner message and return the first valid Google
    Maps URL found (short links like maps.app.goo.gl included)."""
    match = _MAPS_URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(").,!\u201d\u2019")


_MAPS_LABEL_LINE_RE = re.compile(
    r"^(?:google\s*maps?\s*(?:link|location|pin)?|location|map|pin)\W*$", re.IGNORECASE
)


def _maps_place_hint(text: str, maps_url: str) -> str | None:
    """When a shortened/pin-only Maps link carries no place name, look at
    the lines immediately surrounding the URL for a society/building hint."""
    lines = [line.strip() for line in (text or "").splitlines()]
    url_line_index = None
    for index, line in enumerate(lines):
        if maps_url in line:
            url_line_index = index
            break
    if url_line_index is None:
        return None

    for index in (url_line_index - 1, url_line_index + 1):
        if index < 0 or index >= len(lines):
            continue
        candidate = lines[index]
        if not candidate or maps_url in candidate:
            continue
        if _MAPS_LABEL_LINE_RE.match(candidate):
            continue
        if candidate.lower().startswith("community"):
            continue
        return candidate
    return None


def _find(regex, text):
    match = regex.search(text or "")
    return match.group(1).strip() if match else None


def _extract_maintenance_raw(text: str) -> str | None:
    """Return the raw maintenance text exactly as the owner wrote it.

    Covers:
      Maintenance: Water bill
      Maintenance: Included in rent
      Maintenance: 3k
      Maintenance included  → "Included"
    """
    # Full label-colon form takes priority
    raw = _find(_MAINTENANCE_VALUE_RE, text)
    if raw:
        # Strip trailing noise (maps URL, long sentences)
        raw = raw.split("http")[0].split("\n")[0].strip().rstrip(".,;")
        if raw:
            return raw
    if _MAINTENANCE_INCLUDED_RE.search(text):
        return "Included"
    return None


def _extract_floor(text: str) -> str | None:
    """Return the floor description as the owner wrote it.

    Priority:
      1. "Floor: <value>" label
      2. "2 Story Villa" / "2 Storey House"
      3. "G+2"
      4. "3rd floor" inline
      5. "Ground floor"
    """
    # 1. Label form
    raw = _find(_FLOOR_LABEL_RE, text)
    if raw:
        return raw.strip().rstrip(".,;")
    # 2. Story villa/house
    m = _FLOOR_STORY_RE.search(text)
    if m:
        return m.group(1).strip()
    # 3. G+N
    m = _FLOOR_G_RE.search(text)
    if m:
        return m.group(1).upper()
    # 4. Nth floor
    m = _FLOOR_NUM_RE.search(text)
    if m:
        return m.group(1).strip()
    # 5. Ground floor
    m = _FLOOR_GROUND_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


_NULLISH_TENANT = {"n/a", "na", "none", "null", "-", ""}


def _extract_tenant(text: str) -> str | None:
    """Return preferred tenant exactly as stated by owner."""
    raw = _find(_TENANT_PREF_RE, text) or _find(_TENANT_LABEL_RE, text)
    if not raw:
        return None
    cleaned = raw.strip().rstrip(".,;")
    if cleaned.lower() in _NULLISH_TENANT:
        return None
    return cleaned


def _extract_pets(text: str) -> str | None:
    """Return 'Allowed', 'Not Allowed', or None."""
    if _PETS_NOT_ALLOWED_RE.search(text):
        return "Not Allowed"
    if _PETS_ALLOWED_RE.search(text):
        return "Allowed"
    raw = _find(_PETS_LABEL_RE, text)
    if raw:
        lowered = raw.lower()
        if "not" in lowered or "no" == lowered:
            return "Not Allowed"
        if "yes" in lowered or "allow" in lowered:
            return "Allowed"
        return raw.strip().rstrip(".,;") or None
    return None


def _extract_location(text: str) -> str | None:
    """Return the locality/area name from the owner message.

    Tries:
      1. "Location: Sarjapur Road"
      2. "Located in / at / near HSR Layout"
    Skips values that are obviously a full sentence or Maps URL.
    """
    for regex in (_LOCATION_LABEL_RE, _LOCATED_IN_RE):
        raw = _find(regex, text)
        if raw:
            # Reject if it looks like a Maps URL or a long sentence
            if "http" in raw or len(raw) > 50:
                continue
            cleaned = raw.strip().rstrip(".,;")
            if cleaned:
                return cleaned
    return None


def parse_owner_message(text: str) -> dict:
    """Extract every EasyFind template field directly out of the raw
    owner message. Fields that cannot be found are left as None -- the
    formatter omits them rather than guessing a value."""
    text = text or ""
    maps_url        = detect_maps_url(text)
    maps_place_hint = _maps_place_hint(text, maps_url) if maps_url else None

    owner_community = _normalize_owner_community(_find(_COMMUNITY_LABEL_RE, text))
    owner_society   = _find(_SOCIETY_LABEL_RE, text)

    bhk_value = None
    bhk_match = _BHK_RE.search(text)
    if bhk_match:
        bhk_value = normalize_bhk_number(bhk_match.group(1))

    furnishing = None
    lowered = text.lower()
    for keyword in _FURNISHING_KEYWORDS:
        if keyword in lowered:
            furnishing = normalize_furnishing(keyword)
            break

    # ── Money: raw text (preserved) + numeric fallback ────────────────────────
    rent_raw     = _find(_RENT_RAW_RE, text)
    deposit_raw  = _find(_DEPOSIT_RAW_RE, text)
    rent_value   = normalize_money(rent_raw)
    deposit_value = normalize_money(deposit_raw)

    maintenance_raw  = _extract_maintenance_raw(text)
    maintenance_value = normalize_money(maintenance_raw) if maintenance_raw else None

    # maintenance_applicable: True if keyword present, False if included
    maintenance_applicable = None
    if _MAINTENANCE_INCLUDED_RE.search(text):
        maintenance_applicable = False
    elif _MAINTENANCE_KEYWORD_RE.search(text):
        maintenance_applicable = True

    area_value = extract_number(_find(_AREA_RE, text))

    bathrooms_raw = _find(_BATHROOM_LABEL_RE, text) or _find(_BATHROOM_NUM_RE, text)
    bathrooms     = int(bathrooms_raw) if bathrooms_raw else None

    balcony_raw = _find(_BALCONY_LABEL_RE, text) or _find(_BALCONY_NUM_RE, text)
    balcony     = int(balcony_raw) if balcony_raw else None

    available_raw  = _find(_AVAILABLE_RE, text)
    available_from = normalize_available_from(available_raw) if available_raw else None

    brokerage_applicable = None
    if _BROKERAGE_NOT_APPLICABLE_RE.search(text):
        brokerage_applicable = False
    elif _BROKERAGE_APPLICABLE_RE.search(text):
        brokerage_applicable = True

    return {
        # BHK
        "bhk":       bhk_value,
        "bhk_label": bhk_label(bhk_value) if bhk_value is not None else None,
        # Furnishing
        "furnishing": furnishing,
        # Money — raw owner text AND normalised numeric value
        "rent_raw":          rent_raw,
        "rent":              rent_value,
        "deposit_raw":       deposit_raw,
        "deposit":           deposit_value,
        "maintenance_raw":   maintenance_raw,
        "maintenance":       maintenance_value,
        "maintenance_applicable": maintenance_applicable,
        # Area
        "area":       area_value,
        "area_label": area_label(area_value) if area_value is not None else None,
        # Floor — raw owner text
        "floor":   _extract_floor(text),
        # Occupancy
        "bathrooms": bathrooms,
        "balcony":   balcony,
        # Availability
        "available_from": available_raw or available_from,
        # Tenant / Pets
        "tenant_type":  _extract_tenant(text),
        "pets_allowed": _extract_pets(text),
        # Location
        "location": _extract_location(text),
        # Community hints from owner message
        "brokerage_applicable": brokerage_applicable,
        "owner_community": owner_community,
        "owner_society":   owner_society,
        # Maps
        "maps_url":        maps_url,
        "maps_place_hint": maps_place_hint,
        # Raw
        "raw_message": text.strip(),
    }


def extract_place_hint(resolved_url: str) -> tuple[str | None, tuple[float, float] | None]:
    """Pull a place name and/or coordinates out of a *resolved* (i.e.
    already-redirected) Google Maps URL, used by maps_service to decide
    what to search for via the Places API."""
    place_name = None

    name_match = re.search(r"/maps/place/([^/@]+)", resolved_url)
    if name_match:
        place_name = unquote(name_match.group(1).replace("+", " "))
    else:
        query_match = re.search(r"[?&]q=([^&]+)", resolved_url)
        if query_match:
            place_name = unquote_plus(query_match.group(1))

    coords = None
    coord_match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", resolved_url)
    if coord_match:
        coords = (float(coord_match.group(1)), float(coord_match.group(2)))

    return place_name, coords
