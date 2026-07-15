"""Reads/writes the EasyFind inventory sheet.

Hard requirements from the integration spec:
- Never create a new worksheet. Always use the existing worksheet named
  WORKSHEET_NAME. If it doesn't exist, raise an error.
- Columns A-X have a fixed mapping (see COLUMNS below).
- Upsert semantics: if a row with the same Listing URL (column W) already
  exists, update it in place instead of appending a duplicate.
"""
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build

from backend.config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

WORKSHEET_NAME = "April 2026 - March 2027"

# Column order = A..X, with Property ID added in column X.
COLUMNS = [
    "date",                 # A
    "onboarding_status",    # B
    "property_location",    # C
    "society_name",         # D
    "owner_name",           # E
    "contact_number",       # F
    "bhk_label",            # G
    "bathrooms",            # H
    "balcony",              # I
    "area_label",           # J
    "floor_label",          # K
    "furnishing",           # L
    "tenant_preference",    # M
    "veg_non_veg",          # N
    "pets",                 # O
    "rent",                 # P
    "maintenance",          # Q
    "deposit",              # R
    "available_from",       # S
    "negotiations",         # T
    "visit_timings",        # U
    "portal",               # V
    "url",                  # W
    "property_id",          # X
]

URL_COLUMN_INDEX = COLUMNS.index("url")  # W


class GoogleSheetsError(Exception):
    pass


def _get_service():
    if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        raise GoogleSheetsError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured.")
    if not settings.GOOGLE_SHEET_ID:
        raise GoogleSheetsError("GOOGLE_SHEET_ID is not configured.")
    try:
        info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as exc:
        raise GoogleSheetsError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON."
        ) from exc
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _require_worksheet_exists(service):
    """Never create a new worksheet — verify WORKSHEET_NAME exists and
    raise a clear error if it doesn't."""
    sheet_id = settings.GOOGLE_SHEET_ID
    metadata = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    titles = [s["properties"]["title"] for s in metadata.get("sheets", [])]
    if WORKSHEET_NAME not in titles:
        raise GoogleSheetsError(
            f"Worksheet '{WORKSHEET_NAME}' does not exist in spreadsheet "
            f"{sheet_id}. Refusing to create a new worksheet — please "
            f"create it manually (available worksheets: {titles})."
        )


def _row_to_dict(row: list, row_number: int) -> dict:
    data = {col: (row[i] if i < len(row) else None) for i, col in enumerate(COLUMNS)}
    data["_row_number"] = row_number
    return data


def get_existing_rows() -> list:
    """Read back all inventory rows already in the worksheet, for
    duplicate/update matching. Row 1 is assumed to be a header row."""
    service = _get_service()
    _require_worksheet_exists(service)
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=f"'{WORKSHEET_NAME}'!A2:X",
        )
        .execute()
    )
    rows = result.get("values", [])
    # Row 2 in the sheet is index 0 here.
    return [_row_to_dict(row, i + 2) for i, row in enumerate(rows)]


def _dict_to_values(property_dict: dict) -> list:
    values = []
    for col in COLUMNS:
        value = property_dict.get(col)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        values.append("" if value is None else value)
    return values


def _next_empty_row_number(service) -> int:
    """Find the row right after the last row that has any data in A:X.

    Deliberately avoids values().append() — with a fixed target range and
    an explicit row/column write via values().update(), there is no
    ambiguity about which column a new row lands in. (append() was found
    to mis-detect the table's start column and silently shift writes by
    one column when column A is entirely blank, which it is in this
    sheet's historical data.)
    """
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=settings.GOOGLE_SHEET_ID, range=f"'{WORKSHEET_NAME}'!A1:X")
        .execute()
    )
    rows = result.get("values", [])
    return len(rows) + 1


def append_row(property_dict: dict) -> int:
    """Append one property row to WORKSHEET_NAME and return its 1-based
    row number."""
    service = _get_service()
    _require_worksheet_exists(service)
    row_number = _next_empty_row_number(service)
    values = _dict_to_values(property_dict)
    service.spreadsheets().values().update(
        spreadsheetId=settings.GOOGLE_SHEET_ID,
        range=f"'{WORKSHEET_NAME}'!A{row_number}:X{row_number}",
        valueInputOption="RAW",
        body={"values": [values]},
    ).execute()
    return row_number


def update_row(row_number: int, property_dict: dict) -> int:
    """Overwrite an existing row (A:X) in place. Returns the row number."""
    service = _get_service()
    _require_worksheet_exists(service)

    values = _dict_to_values(property_dict)
    service.spreadsheets().values().update(
        spreadsheetId=settings.GOOGLE_SHEET_ID,
        range=f"'{WORKSHEET_NAME}'!A{row_number}:X{row_number}",
        valueInputOption="RAW",
        body={"values": [values]},
    ).execute()
    return row_number


# Columns the automation must never overwrite once a row already exists —
# these are set/managed by brokers, not derived from any extracted value,
# so there's no real data or instruction backing an automated overwrite.
_NEVER_OVERWRITE_ON_UPDATE = {"onboarding_status", "property_id"}


def _merge_for_update(matched_row: dict, property_dict: dict) -> dict:
    """Build the row to write when updating an existing match: only
    overwrite a column if the new extraction actually produced a real
    value for it, and never touch columns in _NEVER_OVERWRITE_ON_UPDATE.
    Everything else keeps whatever was already in the sheet, so an
    update can't blank out data a human already entered."""
    merged = {}
    for col in COLUMNS:
        if col in _NEVER_OVERWRITE_ON_UPDATE:
            merged[col] = matched_row.get(col)
            continue
        new_value = property_dict.get(col)
        if new_value is None or new_value == "":
            merged[col] = matched_row.get(col)
        else:
            merged[col] = new_value
    return merged


def upsert_row(property_dict: dict, matched_row: dict | None) -> tuple[int, str]:
    """Insert a new row, or update `matched_row` in place if given.
    Returns (row_number, action) where action is 'inserted' or 'updated'."""
    if matched_row is not None:
        row_number = matched_row["_row_number"]
        merged = _merge_for_update(matched_row, property_dict)
        update_row(row_number, merged)
        return row_number, "updated"
    row_number = append_row(property_dict)
    return row_number, "inserted"
