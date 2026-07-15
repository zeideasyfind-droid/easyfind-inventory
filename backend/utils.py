import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse


def generate_property_id() -> str:
    """Generate a short, unique property id, e.g. PID12345."""
    return "PID" + uuid.uuid4().hex[:8].upper()


def generate_request_id() -> str:
    """Short hex ID attached to /publish/send responses for log correlation."""
    return uuid.uuid4().hex[:12].upper()


def mask_phone(value: str) -> str:
    """Mask a phone number or numeric ID for safe inclusion in diagnostic
    responses -- shows first 4 and last 2 characters only, replaces the
    middle with asterisks. Never logs or exposes the full value.

    Examples:
        '1234567890'  → '1234****90'
        '12345'       → '1234*5'
        'abc'         → '***'
    """
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return value[:4] + "*" * max(1, len(value) - 6) + value[-2:]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_slug() -> str:
    """Filesystem-safe timestamp used for archive filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


def today_path_parts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")


# Multi-portal support (Task 1 / Task 4 validation: "correct portal is
# identified"). Maps a listing URL's domain to the display name used for
# column V ("portal"). Matched by domain suffix so subdomains (e.g.
# link.mygate.com) still resolve correctly.
_PORTAL_DOMAINS = [
    ("mygate.com", "MyGate"),
    ("99acres.com", "99acres"),
    ("magicbricks.com", "MagicBricks"),
    ("commonfloor.com", "CommonFloor"),
    ("nobroker.in", "NoBroker"),
    ("makaan.com", "Makaan"),
    ("housing.com", "Housing.com"),
]


def detect_portal(url: str) -> str:
    """Identify which supported portal a listing URL belongs to, based on
    its domain. Falls back to the bare domain if it isn't one of the
    known portals, so unexpected sources are still recorded rather than
    silently mislabeled."""
    if not url:
        return "Unknown"
    host = urlparse(url).netloc.lower()
    host = host.split("@")[-1]  # strip any userinfo
    host = host.split(":")[0]   # strip any port
    for domain, name in _PORTAL_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return name
    return host or "Unknown"


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
