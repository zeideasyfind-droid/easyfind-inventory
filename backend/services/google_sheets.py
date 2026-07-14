"""Append normalized property rows to a Google Sheet using a service
account, and read back existing rows for duplicate checking.
"""
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build

from backend.config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_TAB = "Inventory"

COLUMNS = [
    "property_id",
    "extracted_at",
    "portal_url",
    "title",
    "rent",
    "deposit",
    "maintenance",
    "bhk",
    "bathrooms",
    "balcony",
    "furnishing",
    "area",
    "floor",
    "property_type",
    "parking",
    "tenant_preference",
    "pets",
    "available_from",
    "owner_name",
    "contact_number",
    "address",
    "locality",
    "latitude",
    "longitude",
    "amenities",
    "description",
]


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


def _ensure_tab_exists(service):
    sheet_id = settings.GOOGLE_SHEET_ID
    metadata = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    titles = [s["properties"]["title"] for s in metadata.get("sheets", [])]
    if SHEET_TAB not in titles:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": SHEET_TAB}}}]},
        ).execute()


def _ensure_header(service):
    sheet_id = settings.GOOGLE_SHEET_ID
    _ensure_tab_exists(service)
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"{SHEET_TAB}!A1:Z1")
        .execute()
    )
    if not result.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"{SHEET_TAB}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()


def _row_to_dict(row: list) -> dict:
    return {col: (row[i] if i < len(row) else None) for i, col in enumerate(COLUMNS)}


def get_existing_rows() -> list:
    """Read back all inventory rows already in the sheet, for duplicate
    checking. Returns an empty list if the sheet has no data yet."""
    service = _get_service()
    _ensure_header(service)
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=settings.GOOGLE_SHEET_ID, range=f"{SHEET_TAB}!A2:Z")
        .execute()
    )
    rows = result.get("values", [])
    return [_row_to_dict(row) for row in rows]


def append_row(property_dict: dict) -> int:
    """Append one property row and return its 1-based row number."""
    service = _get_service()
    _ensure_header(service)

    values = []
    for col in COLUMNS:
        value = property_dict.get(col)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        values.append("" if value is None else value)

    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=settings.GOOGLE_SHEET_ID,
            range=f"{SHEET_TAB}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [values]},
        )
        .execute()
    )

    updated_range = result.get("updates", {}).get("updatedRange", "")
    row_number = None
    if "!" in updated_range:
        cell_range = updated_range.split("!")[1]
        start_cell = cell_range.split(":")[0]
        digits = "".join(ch for ch in start_cell if ch.isdigit())
        if digits:
            row_number = int(digits)
    return row_number or len(get_existing_rows()) + 1
