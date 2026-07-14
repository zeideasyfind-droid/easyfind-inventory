"""Normalizes raw extracted property data into consistent, typed values."""
import re
from datetime import datetime, timedelta

from backend.utils import extract_number

_FURNISHING_MAP = {
    "unfurnished": "Unfurnished",
    "un-furnished": "Unfurnished",
    "no furnishing": "Unfurnished",
    "semi": "Semi-Furnished",
    "semi-furnished": "Semi-Furnished",
    "semi furnished": "Semi-Furnished",
    "partially furnished": "Semi-Furnished",
    "furnished": "Furnished",
    "fully furnished": "Furnished",
    "full furnished": "Furnished",
}


def _clean_str(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize_money(value):
    return extract_number(value)


def normalize_bhk(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d*\.?\d+", str(value))
    return float(match.group()) if match else None


def normalize_int(value):
    number = extract_number(value)
    return int(round(number)) if number is not None else None


def normalize_furnishing(value):
    if value is None:
        return None
    key = str(value).strip().lower()
    return _FURNISHING_MAP.get(key, _clean_str(value))


def normalize_area(value):
    return extract_number(value)


def normalize_date(value):
    """Best-effort conversion to YYYY-MM-DD. Falls back to the original
    text (e.g. 'Immediate') when it can't be parsed as a date."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"immediate", "immediately", "ready to move"}:
        return "Immediate"

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    match = re.search(r"(\d+)\s*day", text.lower())
    if match:
        days = int(match.group(1))
        return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")

    return text


def normalize_amenities(value):
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r",|;", str(value)) if part.strip()]


def normalize_property(raw: dict) -> dict:
    """Take raw extracted JSON (any missing/messy fields) and return a
    normalized dict matching the Property model's field names."""
    raw = raw or {}
    return {
        "title": _clean_str(raw.get("title")),
        "rent": normalize_money(raw.get("rent")),
        "deposit": normalize_money(raw.get("deposit")),
        "maintenance": normalize_money(raw.get("maintenance")),
        "bhk": normalize_bhk(raw.get("bhk")),
        "bathrooms": normalize_int(raw.get("bathrooms")),
        "balcony": normalize_int(raw.get("balcony")),
        "furnishing": normalize_furnishing(raw.get("furnishing")),
        "area": normalize_area(raw.get("area")),
        "floor": _clean_str(raw.get("floor")),
        "property_type": _clean_str(raw.get("property_type")),
        "parking": _clean_str(raw.get("parking")),
        "tenant_preference": _clean_str(raw.get("tenant_preference")),
        "pets": _clean_str(raw.get("pets")),
        "available_from": normalize_date(raw.get("available_from")),
        "owner_name": _clean_str(raw.get("owner_name")),
        "contact_number": _clean_str(raw.get("contact_number")),
        "address": _clean_str(raw.get("address")),
        "locality": _clean_str(raw.get("locality")),
        "latitude": extract_number(raw.get("latitude")),
        "longitude": extract_number(raw.get("longitude")),
        "amenities": normalize_amenities(raw.get("amenities")),
        "description": _clean_str(raw.get("description")),
    }
