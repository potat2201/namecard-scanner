from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import google_drive


@pytest.fixture(autouse=True)
def clear_drive_caches():
    google_drive._drive_service.cache_clear()
    google_drive._resolve_folder_id.cache_clear()
    yield
    google_drive._drive_service.cache_clear()
    google_drive._resolve_folder_id.cache_clear()


def test_is_drive_configured_false(monkeypatch, tmp_path):
    monkeypatch.setattr(google_drive.settings, "google_drive_credentials_path", None)
    monkeypatch.setattr(google_drive, "oauth_token_path", lambda: tmp_path / "missing-token.json")
    assert google_drive.is_drive_configured() is False


def test_is_drive_configured_true_with_service_account(monkeypatch, tmp_path):
    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    monkeypatch.setattr(google_drive.settings, "google_drive_credentials_path", str(creds))
    monkeypatch.setattr(google_drive, "oauth_token_path", lambda: tmp_path / "missing-token.json")
    assert google_drive.is_drive_configured() is True


def test_drive_name_from_email():
    path = Path("card.jpg")
    assert google_drive._drive_name_from_email("Jane@Example.COM", path) == "jane@example.com.jpg"
    assert google_drive._drive_name_from_email(None, path).startswith("20")
    assert google_drive._drive_name_from_email(None, path).endswith("-card.jpg")


def test_upload_uses_email_filename(monkeypatch, tmp_path: Path):
    image = tmp_path / "card.jpg"
    image.write_bytes(b"fake-image")

    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    monkeypatch.setattr(google_drive.settings, "google_drive_credentials_path", str(creds))
    monkeypatch.setattr(google_drive.settings, "google_drive_folder_id", "folder-123")

    mock_service = MagicMock()
    mock_create = mock_service.files.return_value.create
    mock_create.return_value.execute.return_value = {"id": "drive-file-1"}

    with patch.object(google_drive, "_drive_service", return_value=mock_service):
        file_id = google_drive._upload_namecard_copy_sync(
            image, email="jane@acme.com"
        )

    assert file_id == "drive-file-1"
    metadata = mock_create.call_args.kwargs["body"]
    assert metadata["parents"] == ["folder-123"]
    assert metadata["name"] == "jane@acme.com.jpg"


def test_upload_uses_configured_folder_id(monkeypatch, tmp_path: Path):
    image = tmp_path / "card.jpg"
    image.write_bytes(b"fake-image")

    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    monkeypatch.setattr(google_drive.settings, "google_drive_credentials_path", str(creds))
    monkeypatch.setattr(google_drive.settings, "google_drive_folder_id", "folder-123")
    monkeypatch.setattr(google_drive.settings, "google_drive_folder_name", "namecard")

    mock_service = MagicMock()
    mock_create = mock_service.files.return_value.create
    mock_create.return_value.execute.return_value = {"id": "drive-file-1"}

    with patch.object(google_drive, "_drive_service", return_value=mock_service):
        file_id = google_drive._upload_namecard_copy_sync(
            image, email="jane@acme.com"
        )

    assert file_id == "drive-file-1"
    metadata = mock_create.call_args.kwargs["body"]
    assert metadata["parents"] == ["folder-123"]
    assert metadata["name"] == "jane@acme.com.jpg"


def test_resolve_folder_id_by_name(monkeypatch, tmp_path):
    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    monkeypatch.setattr(google_drive.settings, "google_drive_credentials_path", str(creds))
    monkeypatch.setattr(google_drive.settings, "google_drive_folder_id", None)
    monkeypatch.setattr(google_drive.settings, "google_drive_folder_name", "namecard")

    mock_service = MagicMock()
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "folder-abc", "name": "namecard"}]
    }

    with patch.object(google_drive, "_drive_service", return_value=mock_service):
        folder_id = google_drive._resolve_folder_id()

    assert folder_id == "folder-abc"
