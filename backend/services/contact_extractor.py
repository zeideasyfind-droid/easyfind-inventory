"""Best-effort real-contact-number rescue.

Firecrawl's schema-based extraction sometimes returns a masked or empty
contact number even though a complete, unmasked Indian mobile number is
visible elsewhere on the page (markdown, raw HTML, descriptions,
broker/owner notes, footer/header, etc.). This module does a secondary
text search across whatever page content Firecrawl returned and returns
the first valid, complete Indian mobile number it finds.

It never infers or reconstructs partial/masked numbers: masked numbers
(e.g. "98765XXXXX", "98765*****", "+91 98*** *4210") contain non-digit
placeholder characters where digits should be, so they never match the
digit-only regex below and are correctly left alone.
"""
import re

# Complete Indian mobile numbers are 10 digits starting with 6-9,
# optionally preceded by a country code (+91 / 91) or a trunk "0", and
# sometimes displayed with a space/hyphen after the first 5 digits
# (e.g. "98765 43210"). Lookaround guards avoid matching the middle of a
# longer digit run (order IDs, pin codes glued to other numbers, etc.).
_INDIAN_MOBILE_RE = re.compile(
    r"(?<!\d)(?:\+91[\s-]?|91[\s-]?|0)?([6-9]\d{4}[\s-]?\d{5})(?!\d)"
)


def _is_valid(digits: str) -> bool:
    return len(digits) == 10 and digits[0] in "6789"


def find_indian_mobile(*sources) -> str | None:
    """Search `sources` (any mix of strings; non-strings/empties are
    skipped) in order and return the first valid, complete Indian mobile
    number found, as a plain 10-digit string. Returns None if none of
    the sources contain one."""
    for source in sources:
        if not source or not isinstance(source, str):
            continue
        for match in _INDIAN_MOBILE_RE.finditer(source):
            digits = re.sub(r"[\s-]", "", match.group(1))
            if _is_valid(digits):
                return digits
    return None
