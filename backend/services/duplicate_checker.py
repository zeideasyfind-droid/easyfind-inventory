"""Duplicate detection against previously-ingested inventory rows.

Priority order (first match wins):
  1. Listing URL
  2. Contact number
  3. Property address
  4. Combination of Rent + Area + BHK
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


def find_duplicate(candidate: dict, existing_rows: list) -> dict | None:
    """`candidate` is the normalized property dict (plus portal_url).
    `existing_rows` is a list of dicts with the same keys, typically read
    back from Google Sheets. Returns the matching existing row, or None.
    """
    candidate_url = _norm(candidate.get("portal_url"))
    candidate_contact = _norm(candidate.get("contact_number"))
    candidate_address = _norm(candidate.get("address"))
    candidate_combo = (
        _norm_number(candidate.get("rent")),
        _norm_number(candidate.get("area")),
        _norm_number(candidate.get("bhk")),
    )

    if candidate_url:
        for row in existing_rows:
            if _norm(row.get("portal_url")) == candidate_url:
                return row

    if candidate_contact:
        for row in existing_rows:
            if _norm(row.get("contact_number")) == candidate_contact:
                return row

    if candidate_address:
        for row in existing_rows:
            if _norm(row.get("address")) == candidate_address:
                return row

    if all(value is not None for value in candidate_combo):
        for row in existing_rows:
            row_combo = (
                _norm_number(row.get("rent")),
                _norm_number(row.get("area")),
                _norm_number(row.get("bhk")),
            )
            if None not in row_combo and row_combo == candidate_combo:
                return row

    return None
