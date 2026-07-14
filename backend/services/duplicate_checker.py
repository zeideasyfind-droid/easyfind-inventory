"""Duplicate detection against rows already in the Google Sheet.

Per the integration spec, this is an upsert rule, not a reject rule:
  1. Compare using Listing URL (column W). If it matches, the caller
     should UPDATE that row instead of inserting a new one.
  2. Otherwise (candidate has no URL, or the URL doesn't match any
     existing row), fall back to Contact Number + Society Name + Rent.

The fallback matters in practice: a lot of the sheet's pre-existing rows
were entered manually before this tool existed and have a placeholder
like "MyGate" / "Mygate" in the URL column instead of a real link (see
rows such as 486-488). Those rows can never match on URL, so without the
contact/society/rent fallback, re-extracting one of those listings would
always be treated as brand new -> a duplicate row gets inserted with the
default onboarding status, which looks exactly like the human-entered
Column B status ("Done", "Not Available", ...) got wiped even though the
original row was never touched.
"""

import re

_MONEY_LAKH_RE = re.compile(r"([\d.]+)\s*l(?:akh)?s?\b", re.IGNORECASE)
_MONEY_THOUSAND_RE = re.compile(r"([\d.]+)\s*k\b", re.IGNORECASE)
_MONEY_DIGITS_RE = re.compile(r"[\d.]+")


def _norm(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _norm_number(value):
    """Coerce a rent-like value into a comparable float, whether it's
    already numeric (freshly normalized) or free text like "50k" / "3L"
    / "50,000" (legacy manually-entered sheet rows). Returns None if no
    number can be extracted at all."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)

    text = str(value).strip()
    if not text:
        return None

    lakh_match = _MONEY_LAKH_RE.search(text)
    if lakh_match:
        return round(float(lakh_match.group(1)) * 100000, 2)

    thousand_match = _MONEY_THOUSAND_RE.search(text)
    if thousand_match:
        return round(float(thousand_match.group(1)) * 1000, 2)

    digits_match = _MONEY_DIGITS_RE.search(text.replace(",", ""))
    if digits_match:
        return round(float(digits_match.group()), 2)

    return None


def _match_by_contact_society_rent(candidate: dict, existing_rows: list) -> dict | None:
    candidate_contact = _norm(candidate.get("contact_number"))
    candidate_society = _norm(candidate.get("society_name"))
    candidate_rent = _norm_number(candidate.get("rent"))

    if not (candidate_contact and candidate_society and candidate_rent is not None):
        return None

    for row in existing_rows:
        if (
            _norm(row.get("contact_number")) == candidate_contact
            and _norm(row.get("society_name")) == candidate_society
            and _norm_number(row.get("rent")) == candidate_rent
        ):
            return row

    return None


def find_matching_row(candidate: dict, existing_rows: list) -> dict | None:
    """`candidate` uses the same field names as the sheet columns (url,
    contact_number, society_name, rent). `existing_rows` come from
    google_sheets.get_existing_rows(). Returns the matching row dict
    (including its `_row_number`), or None if there's no match."""
    candidate_url = _norm(candidate.get("url"))
    if candidate_url:
        for row in existing_rows:
            if _norm(row.get("url")) == candidate_url:
                return row

    return _match_by_contact_society_rent(candidate, existing_rows)
