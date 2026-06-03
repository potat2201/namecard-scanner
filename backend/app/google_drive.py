from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.config import BASE_DIR, DATA_DIR, settings

logger = logging.getLogger(__name__)

SCOPES = ("https://www.googleapis.com/auth/drive.file",)
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_OAUTH_TOKEN_PATH = DATA_DIR / "google_drive_token.json"
UNKNOWN_COMPANY_FOLDER = "Unknown Company"


class GoogleDriveError(Exception):
    """Raised when a Google Drive upload or lookup fails."""


def _resolve_path(raw: Optional[str], fallback: Optional[Path] = None) -> Optional[Path]:
    if not raw:
        return fallback
    path = Path(raw).expanduser()
    if path.is_file():
        return path
    for candidate in (BASE_DIR.parent / raw, BASE_DIR / raw, BASE_DIR / Path(raw).name):
        if candidate.is_file():
            return candidate
    return path if path.is_file() else None


def oauth_token_path() -> Path:
    resolved = _resolve_path(settings.google_drive_oauth_token_path)
    return resolved or DEFAULT_OAUTH_TOKEN_PATH


def _oauth_client_path() -> Optional[Path]:
    return _resolve_path(settings.google_drive_oauth_client_path)


def _service_account_path() -> Optional[Path]:
    return _resolve_path(settings.google_drive_credentials_path)


def is_drive_configured() -> bool:
    if oauth_token_path().is_file():
        return True
    return _service_account_path() is not None


def _save_oauth_token(creds: UserCredentials) -> None:
    oauth_token_path().parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }
    oauth_token_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_oauth_credentials() -> Optional[UserCredentials]:
    token_path = oauth_token_path()
    if not token_path.is_file():
        return None

    data = json.loads(token_path.read_text(encoding="utf-8"))
    creds = UserCredentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes") or list(SCOPES),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_oauth_token(creds)
    return creds


def _build_credentials() -> Any:
    oauth = _load_oauth_credentials()
    if oauth:
        return oauth

    sa_path = _service_account_path()
    if sa_path:
        return ServiceAccountCredentials.from_service_account_file(str(sa_path), scopes=SCOPES)

    raise GoogleDriveError("Google Drive is not configured")


def using_oauth() -> bool:
    return oauth_token_path().is_file()


@lru_cache(maxsize=1)
def _drive_service():
    credentials = _build_credentials()
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _folder_not_found_message() -> str:
    folder_name = settings.google_drive_folder_name
    if using_oauth():
        return (
            f"Google Drive folder '{folder_name}' not found in your Drive. "
            f"Create the folder or set GOOGLE_DRIVE_FOLDER_ID."
        )
    return (
        f"Google Drive folder '{folder_name}' not found. "
        "For personal Gmail, use OAuth (see README). "
        "Service accounts only upload to Shared drives, not My Drive folders."
    )


@lru_cache(maxsize=1)
def _resolve_folder_id() -> str:
    if settings.google_drive_folder_id:
        return settings.google_drive_folder_id

    folder_name = settings.google_drive_folder_name
    service = _drive_service()
    escaped_name = folder_name.replace("'", "\\'")
    query = f"name = '{escaped_name}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    results = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=10,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        )
        .execute()
    )
    files = results.get("files", [])
    if not files:
        raise GoogleDriveError(_folder_not_found_message())
    if len(files) > 1:
        raise GoogleDriveError(
            f"Multiple Google Drive folders named '{folder_name}' found. "
            "Set GOOGLE_DRIVE_FOLDER_ID to the exact folder ID."
        )
    return files[0]["id"]


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _sanitize_folder_name(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " -_&." else "_" for c in name.strip())
    cleaned = " ".join(cleaned.split())
    return cleaned[:200] or UNKNOWN_COMPANY_FOLDER


def _company_folder_name(company: Optional[str]) -> str:
    if company and company.strip():
        return _sanitize_folder_name(company)
    return UNKNOWN_COMPANY_FOLDER


def _find_child_folder(service: Any, parent_id: str, folder_name: str) -> Optional[str]:
    escaped = _escape_drive_query(folder_name)
    query = (
        f"name = '{escaped}' and mimeType = '{FOLDER_MIME}' "
        f"and '{parent_id}' in parents and trashed = false"
    )
    results = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=10,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        )
        .execute()
    )
    files = results.get("files", [])
    if not files:
        return None
    if len(files) > 1:
        logger.warning(
            "Multiple Drive folders named '%s' under parent %s; using first match",
            folder_name,
            parent_id,
        )
    return files[0]["id"]


def _get_or_create_company_folder(service: Any, parent_id: str, company: Optional[str]) -> str:
    folder_name = _company_folder_name(company)
    existing_id = _find_child_folder(service, parent_id, folder_name)
    if existing_id:
        return existing_id

    created = (
        service.files()
        .create(
            body={
                "name": folder_name,
                "mimeType": FOLDER_MIME,
                "parents": [parent_id],
            },
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    folder_id = created.get("id")
    if not folder_id:
        raise GoogleDriveError(f"Failed to create Google Drive folder '{folder_name}'")
    logger.info("Created Google Drive company folder '%s' (id=%s)", folder_name, folder_id)
    return folder_id


def _drive_name_from_email(email: Optional[str], local_path: Path) -> str:
    ext = local_path.suffix or ".jpg"
    if email:
        safe = email.strip().lower()
        safe = "".join(c if c.isalnum() or c in "@._+-" else "_" for c in safe).strip("_")
        if safe:
            return f"{safe}{ext}"
    stem = local_path.stem or "namecard"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{stem}{ext}"


def _upload_namecard_copy_sync(
    local_path: Path,
    *,
    email: Optional[str] = None,
    company: Optional[str] = None,
    original_filename: Optional[str] = None,
) -> str:
    service = _drive_service()
    root_folder_id = _resolve_folder_id()
    folder_id = _get_or_create_company_folder(service, root_folder_id, company)

    if email:
        drive_name = _drive_name_from_email(email, local_path)
    else:
        ext = local_path.suffix or ".jpg"
        stem = Path(original_filename or local_path.name).stem or "namecard"
        safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem).strip("_")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        drive_name = f"{timestamp}-{safe_stem or 'namecard'}{ext}"

    mime_type, _ = mimetypes.guess_type(str(local_path))
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    metadata = {"name": drive_name, "parents": [folder_id]}
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
    try:
        created = (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
    except Exception as exc:
        message = str(exc)
        if "storageQuotaExceeded" in message or "Service Accounts do not have storage quota" in message:
            raise GoogleDriveError(
                "Service account cannot upload to personal Google Drive. "
                "Run: python scripts/google_drive_auth.py (OAuth setup in README)."
            ) from exc
        raise

    file_id = created.get("id")
    if not file_id:
        raise GoogleDriveError("Google Drive upload did not return a file ID")
    return file_id


async def upload_namecard_copy(
    local_path: Path,
    *,
    email: Optional[str] = None,
    company: Optional[str] = None,
    original_filename: Optional[str] = None,
) -> str:
    """Upload a namecard image into a company subfolder under the configured Drive folder."""
    if not is_drive_configured():
        raise GoogleDriveError("Google Drive is not configured")

    return await asyncio.to_thread(
        _upload_namecard_copy_sync,
        local_path,
        email=email,
        company=company,
        original_filename=original_filename,
    )
