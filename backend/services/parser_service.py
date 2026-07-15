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
# The gap between the label and the number is restricted to non-newline
# characters and requires an actual digit -- otherwise "...for rent." in
# an earlier sentence (dot, no digit) would match before the real
# "Rent: 45000" line and produce a bogus/empty amount.
_RENT_RE = re.compile(
    r"\brent\b[^\n\d]{0,20}?(\d[\d,\.]*\s*(?:k|l|lakh|lakhs)?)", re.IGNORECASE
)
_DEPOSIT_RE = re.compile(
    r"\bdeposit\b[^\n\d]{0,20}?(\d[\d,\.]*\s*(?:k|l|lakh|lakhs)?)", re.IGNORECASE
)
_AREA_RE = re.compile(r"([\d,\.]+)\s*(?:sq\.?\s*ft\.?|sqft|sft)", re.IGNORECASE)
# Both "2 Bathrooms" and "Bathroom: 2" style messages occur -- try the
# label-first form (more common in copy-pasted owner templates) before
# falling back to number-first. The number/label gap excludes newlines so
# a count from an unrelated earlier line can never bleed into this field.
_BATHROOM_LABEL_RE = re.compile(r"(?:bathroom|toilet|washroom)s?[:\-]?[ \t]*(\d+)", re.IGNORECASE)
_BATHROOM_NUM_RE = re.compile(r"(\d+)[ \t]*(?:bathroom|toilet|washroom)s?", re.IGNORECASE)
_BALCONY_LABEL_RE = re.compile(r"balcon\w*[:\-]?[ \t]*(\d+)", re.IGNORECASE)
_BALCONY_NUM_RE = re.compile(r"(\d+)[ \t]*balcon", re.IGNORECASE)
_AVAILABLE_RE = re.compile(r"available(?:\s*from)?[:\-]?\s*([^\n,]+)", re.IGNORECASE)
_MAINTENANCE_INCLUDED_RE = re.compile(r"maintenance\s+included", re.IGNORECASE)
_MAINTENANCE_KEYWORD_RE = re.compile(r"maintenance", re.IGNORECASE)
_BROKERAGE_APPLICABLE_RE = re.compile(r"brokerage\s+applicable", re.IGNORECASE)
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

# Owner messages often state the community type themselves ("Community:
# Gated Community"). This is the fallback used when Google Maps
# enrichment can't resolve a place at all -- never used to override a
# successful Maps lookup, only to avoid discarding known-good information
# down to "Unknown" (08_GOOGLE_MAPS_ENRICHMENT.md).
_COMMUNITY_LABEL_RE = re.compile(r"\bcommunity\b[:\-]?\s*([^\n]+)", re.IGNORECASE)
_SOCIETY_LABEL_RE = re.compile(
    r"\b(?:society|apartment|complex|building)\s*(?:name)?[:\-]\s*([^\n]+)", re.IGNORECASE
)
_SEMI_GATED_HINTS = ("semi-gated", "semi gated")
_GATED_HINTS = ("gated",)
_STANDALONE_HINTS = ("standalone", "stand-alone", "independent")


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


# Lines that are just a label for the link itself, not a place name -- if
# the line right before/after the Maps URL is one of these (or is the URL
# line itself), it is never treated as a place-name hint.
_MAPS_LABEL_LINE_RE = re.compile(
    r"^(?:google\s*maps?\s*(?:link|location|pin)?|location|map|pin)\W*$", re.IGNORECASE
)


def _maps_place_hint(text: str, maps_url: str) -> str | None:
    """When a shortened/pin-only Maps link carries no place name of its
    own, owners often paste the society/building name as plain text right
    next to the link (this is exactly what WhatsApp's own "share location"
    message looks like: name on one line, link on the next). Look at the
    lines immediately surrounding the URL for such a hint."""
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


def parse_owner_message(text: str) -> dict:
    """Extract every EasyFind template field directly out of the raw
    owner message. Fields that cannot be found are left as None -- the
    formatter omits them rather than guessing a value."""
    text = text or ""
    maps_url = detect_maps_url(text)
    maps_place_hint = _maps_place_hint(text, maps_url) if maps_url else None

    owner_community = _normalize_owner_community(_find(_COMMUNITY_LABEL_RE, text))
    owner_society = _find(_SOCIETY_LABEL_RE, text)

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

    rent_value = normalize_money(_find(_RENT_RE, text))
    deposit_value = normalize_money(_find(_DEPOSIT_RE, text))
    area_value = extract_number(_find(_AREA_RE, text))

    bathrooms_raw = _find(_BATHROOM_LABEL_RE, text) or _find(_BATHROOM_NUM_RE, text)
    bathrooms = int(bathrooms_raw) if bathrooms_raw else None

    balcony_raw = _find(_BALCONY_LABEL_RE, text) or _find(_BALCONY_NUM_RE, text)
    balcony = int(balcony_raw) if balcony_raw else None

    available_raw = _find(_AVAILABLE_RE, text)
    available_from = normalize_available_from(available_raw) if available_raw else None

    maintenance_applicable = None
    if _MAINTENANCE_INCLUDED_RE.search(text):
        maintenance_applicable = False
    elif _MAINTENANCE_KEYWORD_RE.search(text):
        maintenance_applicable = True

    brokerage_applicable = None
    if _BROKERAGE_NOT_APPLICABLE_RE.search(text):
        brokerage_applicable = False
    elif _BROKERAGE_APPLICABLE_RE.search(text):
        brokerage_applicable = True

    return {
        "bhk": bhk_value,
        "bhk_label": bhk_label(bhk_value) if bhk_value is not None else None,
        "furnishing": furnishing,
        "rent": rent_value,
        "deposit": deposit_value,
        "maintenance_applicable": maintenance_applicable,
        "area": area_value,
        "area_label": area_label(area_value) if area_value is not None else None,
        "bathrooms": bathrooms,
        "balcony": balcony,
        "available_from": available_from,
        "brokerage_applicable": brokerage_applicable,
        "maps_url": maps_url,
        "maps_place_hint": maps_place_hint,
        "owner_community": owner_community,
        "owner_society": owner_society,
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
