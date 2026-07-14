"""Archives every extraction as a JSON file before it is written to
Google Sheets. Uploads to Google Drive when GOOGLE_DRIVE_FOLDER_ID is
configured (preferred); otherwise archives to local disk under
archives/YYYY/MM/DD/, per the implementation spec.
"""
import io
import json
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from backend.config import settings
from backend.utils import timestamp_slug, today_path_parts

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
ARCHIVE_ROOT = Path(__file__).resolve().parent.parent.parent / "archives"


def _local_archive_path() -> Path:
    year, month, day = today_path_parts()
    directory = ARCHIVE_ROOT / year / month / day
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"property_{timestamp_slug()}.json"


def _archive_locally(payload: dict) -> str:
    path = _local_archive_path()
    path.write_text(json.dumps(payload, indent=2, default=str))
    return str(path)


def _get_drive_service():
    info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _archive_to_drive(payload: dict) -> str:
    service = _get_drive_service()
    year, month, day = today_path_parts()
    filename = f"property_{timestamp_slug()}.json"

    body = json.dumps(payload, indent=2, default=str).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(body), mimetype="application/json")
    file_metadata = {
        "name": filename,
        "parents": [settings.GOOGLE_DRIVE_FOLDER_ID],
        "description": f"archives/{year}/{month}/{day}/{filename}",
    }
    created = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id, webViewLink")
        .execute()
    )
    return created.get("webViewLink") or created.get("id")


def archive_property(payload: dict) -> str:
    """Archive the extracted+normalized property JSON. Returns a
    location string (local path or Drive link) for logging/debugging.
    Every extraction is archived before it reaches Google Sheets."""
    if settings.GOOGLE_DRIVE_FOLDER_ID and settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        try:
            return _archive_to_drive(payload)
        except Exception:
            # Fall back to local storage so an extraction is never lost
            # just because Drive is temporarily unavailable.
            return _archive_locally(payload)
    return _archive_locally(payload)
