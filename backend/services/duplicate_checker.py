"""Duplicate detection against rows already in the Google Sheet.

Per the integration spec, this is an upsert rule, not a reject rule:
  1. Compare using Listing URL (column W). If it matches, the caller
     should UPDATE that row instead of inserting a new one.
  2. If the candidate has no URL, compare Contact Number + Society Name
     + Rent instead.
"""


def _norm(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _norm_number(value):
    """Coerce a value (possibly a string read back from Google Sheets)
    into a float for comparison, or None if it isn't numeric."""
    if value is None or value == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
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
        return None

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
