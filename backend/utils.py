import re
import uuid
from datetime import datetime, timezone


def generate_property_id() -> str:
    """Generate a short, unique property id, e.g. PID12345."""
    return "PID" + uuid.uuid4().hex[:8].upper()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_slug() -> str:
    """Filesystem-safe timestamp used for archive filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


def today_path_parts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")


_NUMERIC_RE = re.compile(r"[-+]?\d*\.?\d+")


def extract_number(value):
    """Pull the first numeric value out of a string like '₹25,000/month'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", "")
    match = _NUMERIC_RE.search(cleaned)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None
