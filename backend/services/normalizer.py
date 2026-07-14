"""Normalizes raw extracted property data into the exact values required
by the EasyFind Google Sheet column mapping (columns A-W).
"""
import re
from datetime import datetime, timezone

from backend.utils import extract_number


_NULLISH_STRINGS = {"null", "none", "n/a", "na", "nil", "-"}


def _clean_str(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() in _NULLISH_STRINGS:
        return None
    return value


# ---------------------------------------------------------------- money ---

_LAKH_RE = re.compile(r"([\d.]+)\s*l(?:akh)?s?\b", re.IGNORECASE)
_THOUSAND_RE = re.compile(r"([\d.]+)\s*k\b", re.IGNORECASE)
_INCLUDED_RE = re.compile(r"includ", re.IGNORECASE)


def normalize_money(value):
    """Parse rent/deposit/maintenance values like '65k', '3L', '25,000',
    'Included' (-> 0) into a plain numeric value."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    if _INCLUDED_RE.search(text):
        return 0.0

    lakh_match = _LAKH_RE.search(text)
    if lakh_match:
        return float(lakh_match.group(1)) * 100000

    thousand_match = _THOUSAND_RE.search(text)
    if thousand_match:
        return float(thousand_match.group(1)) * 1000

    return extract_number(text)


# ------------------------------------------------------------------ bhk ---

_ALLOWED_BHK = {1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5}


def normalize_bhk_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d*\.?\d+", str(value))
    return float(match.group()) if match else None


def bhk_label(bhk_value):
    """Column G: '1 BHK' .. '4+ BHK' / '5 BHK'."""
    if bhk_value is None:
        return None
    if bhk_value > 4 and bhk_value < 5:
        return "4+ BHK"
    if bhk_value == int(bhk_value):
        return f"{int(bhk_value)} BHK"
    return f"{bhk_value:g} BHK"


# ------------------------------------------------------------ int counts ---


def normalize_int(value, default=None):
    number = extract_number(value)
    if number is None:
        return default
    return int(round(number))


# ------------------------------------------------------------------ area --


def normalize_area_number(value):
    return extract_number(value)


def area_label(area_value):
    """Column J: numeric value with 'Sq. Ft.' formatting."""
    if area_value is None:
        return None
    if area_value == int(area_value):
        return f"{int(area_value)} Sq. Ft."
    return f"{area_value:g} Sq. Ft."


# ----------------------------------------------------------------- floor --


def floor_label(floor, total_floors):
    """Column K: 'Floor/Total Floors', e.g. '3/10'."""
    floor_num = extract_number(floor)
    total_num = extract_number(total_floors)
    if floor_num is None and total_num is None:
        return None
    floor_str = str(int(floor_num)) if floor_num is not None else "?"
    total_str = str(int(total_num)) if total_num is not None else "?"
    return f"{floor_str}/{total_str}"


# ------------------------------------------------------------- furnishing --

_FURNISHING_MAP = {
    "unfurnished": "Unfurnished",
    "un-furnished": "Unfurnished",
    "no furnishing": "Unfurnished",
    "semi": "Semi Furnished",
    "semi-furnished": "Semi Furnished",
    "semifurnished": "Semi Furnished",
    "semi furnished": "Semi Furnished",
    "partially furnished": "Partially Furnished",
    "partly furnished": "Partially Furnished",
    "furnished": "Fully Furnished",
    "fully furnished": "Fully Furnished",
    "full furnished": "Fully Furnished",
}


def normalize_furnishing(value):
    if value is None:
        return None
    key = str(value).strip().lower()
    return _FURNISHING_MAP.get(key, _clean_str(value))


# ------------------------------------------------------- tenant preference-

_TENANT_MAP = {
    "family": "Family",
    "families": "Family",
    "bachelor": "Bachelor",
    "bachelors": "Bachelor",
    "male bachelor": "Bachelor",
    "female bachelor": "Female Bachelor",
    "female bachelors": "Female Bachelor",
    "company": "Company Lease",
    "company lease": "Company Lease",
    "corporate lease": "Company Lease",
    "anyone": "Open For All",
    "any": "Open For All",
    "open": "Open For All",
    "open for all": "Open For All",
    "all": "Open For All",
}


def normalize_tenant_preference(value):
    if value is None:
        return None
    key = str(value).strip().lower()
    return _TENANT_MAP.get(key, _clean_str(value))


# --------------------------------------------------------------- veg/non --

_VEG_MAP = {
    "veg": "Veg",
    "vegetarian": "Veg",
    "non veg": "Non Veg",
    "non-veg": "Non Veg",
    "nonveg": "Non Veg",
    "non vegetarian": "Non Veg",
    "any": "Any",
    "anyone": "Any",
    "both": "Any",
}


def normalize_veg_non_veg(value):
    if value is None:
        return None
    key = str(value).strip().lower()
    return _VEG_MAP.get(key, _clean_str(value))


# -------------------------------------------------------------------- pets

_PETS_MAP = {
    "allowed": "Allowed",
    "yes": "Allowed",
    "pet friendly": "Allowed",
    "not allowed": "Not Allowed",
    "no": "Not Allowed",
    "not pet friendly": "Not Allowed",
}


def normalize_pets(value):
    if value is None:
        return None
    key = str(value).strip().lower()
    return _PETS_MAP.get(key, _clean_str(value))


# ------------------------------------------------------------ available --

_IMMEDIATE_VALUES = {
    "immediate",
    "immediately",
    "ready to occupy",
    "ready to move",
    "available now",
}


def normalize_available_from(value, today=None):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    today = today or datetime.now(timezone.utc).date()
    if text.lower() in _IMMEDIATE_VALUES:
        return today.isoformat()

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue

    # Not a recognizable immediate phrase or parseable date: keep as-is
    # so a genuine future date/phrase isn't lost.
    return text


# ------------------------------------------------------------------ main --


def normalize_property(raw: dict, today=None) -> dict:
    """Take raw extracted JSON and return a dict of normalized values
    keyed by the internal field names used in models.Property /
    google_sheets column mapping."""
    raw = raw or {}
    today = today or datetime.now(timezone.utc).date()

    bhk_value = normalize_bhk_number(raw.get("bhk"))
    area_value = normalize_area_number(raw.get("area"))

    return {
        "date": today.isoformat(),
        "onboarding_status": "Done WFP",
        "property_location": _clean_str(raw.get("property_location")),
        "society_name": _clean_str(raw.get("society_name")),
        "owner_name": _clean_str(raw.get("owner_name")),
        "contact_number": _clean_str(raw.get("contact_number")),
        "bhk": bhk_value,
        "bhk_label": bhk_label(bhk_value),
        "bathrooms": normalize_int(raw.get("bathrooms")),
        "balcony": normalize_int(raw.get("balcony"), default=0),
        "area": area_value,
        "area_label": area_label(area_value),
        "floor_label": floor_label(raw.get("floor"), raw.get("total_floors")),
        "furnishing": normalize_furnishing(raw.get("furnishing")),
        "tenant_preference": normalize_tenant_preference(raw.get("tenant_preference")),
        "veg_non_veg": normalize_veg_non_veg(raw.get("veg_non_veg")),
        "pets": normalize_pets(raw.get("pets")),
        "rent": normalize_money(raw.get("rent")),
        "maintenance": normalize_money(raw.get("maintenance")),
        "deposit": normalize_money(raw.get("deposit")),
        "available_from": normalize_available_from(raw.get("available_from"), today=today),
        "negotiations": _clean_str(raw.get("negotiations")),
        "visit_timings": _clean_str(raw.get("visit_timings")),
        "portal": "Housing.com",
    }
