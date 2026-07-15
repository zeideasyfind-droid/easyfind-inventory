"""Archives every extraction before it is written to Google Sheets.
Uploads to Google Drive when GOOGLE_DRIVE_FOLDER_ID is configured
(preferred); otherwise archives to local disk under archives/.
"""
import io
import json
import subprocess
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from backend.config import settings

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
ARCHIVE_ROOT = Path(__file__).resolve().parent.parent.parent / "archives"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def detect_application_version() -> str | None:
    for command in (
        ["git", "rev-parse", "HEAD"],
        ["git", "describe", "--always", "--dirty"],
    ):
        try:
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            value = result.stdout.strip()
            if value:
                return value
        except Exception:
            continue
    return None


def _archive_folder_name(property_id: str) -> str:
    return property_id


def _local_archive_dir(property_id: str) -> Path:
    directory = ARCHIVE_ROOT / _archive_folder_name(property_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_archive_files(base_path: Path, normalized: dict, firecrawl_response: dict, markdown: str, metadata: dict):
    (base_path / "normalized.json").write_text(
        json.dumps(normalized, indent=2, default=str), encoding="utf-8"
    )
    (base_path / "firecrawl_response.json").write_text(
        json.dumps(firecrawl_response, indent=2, default=str), encoding="utf-8"
    )
    (base_path / "markdown.md").write_text(markdown or "", encoding="utf-8")
    (base_path / "metadata.json").write_text(
        json.dumps(metadata, indent=2, default=str), encoding="utf-8"
    )


def _archive_locally(property_id: str, normalized: dict, firecrawl_response: dict, markdown: str, metadata: dict) -> str:
    path = _local_archive_dir(property_id)
    _write_archive_files(path, normalized, firecrawl_response, markdown, metadata)
    return str(path)


def _get_drive_service():
    info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _find_drive_folder(service, name: str, parent_id: str) -> str | None:
    query = (
        "mimeType = 'application/vnd.google-apps.folder' and "
        f"name = '{name.replace("'", "\\'")}' and "
        f"'{parent_id}' in parents and trashed = false"
    )
    result = service.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def _ensure_drive_folder(service, name: str, parent_id: str) -> str:
    existing = _find_drive_folder(service, name, parent_id)
    if existing:
        return existing
    created = service.files().create(
        body={
            "name": name,
            "parents": [parent_id],
            "mimeType": "application/vnd.google-apps.folder",
        },
        fields="id",
    ).execute()
    return created["id"]


def _upload_text_file(service, folder_id: str, name: str, body: str, mime_type: str):
    media = MediaIoBaseUpload(io.BytesIO(body.encode("utf-8")), mimetype=mime_type)
    service.files().create(
        body={"name": name, "parents": [folder_id]},
        media_body=media,
        fields="id",
    ).execute()


def _archive_to_drive(property_id: str, normalized: dict, firecrawl_response: dict, markdown: str, metadata: dict) -> str:
    service = _get_drive_service()
    folder_id = _ensure_drive_folder(service, _archive_folder_name(property_id), settings.GOOGLE_DRIVE_FOLDER_ID)
    _upload_text_file(service, folder_id, "normalized.json", json.dumps(normalized, indent=2, default=str), "application/json")
    _upload_text_file(service, folder_id, "firecrawl_response.json", json.dumps(firecrawl_response, indent=2, default=str), "application/json")
    _upload_text_file(service, folder_id, "markdown.md", markdown or "", "text/markdown")
    _upload_text_file(service, folder_id, "metadata.json", json.dumps(metadata, indent=2, default=str), "application/json")
    return folder_id


def archive_property(property_id: str, normalized: dict, firecrawl_response: dict, markdown: str, metadata: dict) -> str:
    """Archive one extraction under a PID-named folder. Returns a location
    string (local path or Drive folder id) for logging/debugging."""
    if settings.GOOGLE_DRIVE_FOLDER_ID and settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        try:
            return _archive_to_drive(property_id, normalized, firecrawl_response, markdown, metadata)
        except Exception:
            return _archive_locally(property_id, normalized, firecrawl_response, markdown, metadata)
    return _archive_locally(property_id, normalized, firecrawl_response, markdown, metadata)
