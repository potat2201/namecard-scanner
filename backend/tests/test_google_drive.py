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


def test_domain_folder_name_from_email():
    assert (
        google_drive._domain_folder_name(email="Jane@Example.COM")
        == "example.com"
    )


def test_domain_folder_name_from_website():
    assert (
        google_drive._domain_folder_name(website="https://www.acme.co.uk/about")
        == "acme.co.uk"
    )


def test_domain_folder_name_unknown():
    assert (
        google_drive._domain_folder_name(email=None, website=None)
        == google_drive.UNKNOWN_DOMAIN_FOLDER
    )


def test_get_or_create_domain_folder_reuses_existing(monkeypatch, tmp_path):
    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    monkeypatch.setattr(google_drive.settings, "google_drive_credentials_path", str(creds))

    mock_service = MagicMock()
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "domain-folder-1", "name": "acme.com"}]
    }

    with patch.object(google_drive, "_drive_service", return_value=mock_service):
        folder_id = google_drive._get_or_create_domain_folder(
            mock_service,
            "root-folder",
            email="jane@acme.com",
        )

    assert folder_id == "domain-folder-1"
    mock_service.files.return_value.create.assert_not_called()


def test_get_or_create_domain_folder_creates_when_missing(monkeypatch, tmp_path):
    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    monkeypatch.setattr(google_drive.settings, "google_drive_credentials_path", str(creds))

    mock_service = MagicMock()
    mock_service.files.return_value.list.return_value.execute.return_value = {"files": []}
    mock_service.files.return_value.create.return_value.execute.return_value = {
        "id": "new-domain-folder"
    }

    with patch.object(google_drive, "_drive_service", return_value=mock_service):
        folder_id = google_drive._get_or_create_domain_folder(
            mock_service,
            "root-folder",
            website="https://newco.io",
        )

    assert folder_id == "new-domain-folder"
    create_body = mock_service.files.return_value.create.call_args.kwargs["body"]
    assert create_body["name"] == "newco.io"
    assert create_body["parents"] == ["root-folder"]


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
        with patch.object(
            google_drive,
            "_get_or_create_domain_folder",
            return_value="domain-folder-99",
        ) as mock_domain_folder:
            file_id = google_drive._upload_namecard_copy_sync(
                image, email="jane@acme.com", website="https://acme.com"
            )

    mock_domain_folder.assert_called_once()
    assert file_id == "drive-file-1"
    metadata = mock_create.call_args.kwargs["body"]
    assert metadata["parents"] == ["domain-folder-99"]
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
        with patch.object(
            google_drive,
            "_get_or_create_domain_folder",
            return_value="domain-folder-99",
        ):
            file_id = google_drive._upload_namecard_copy_sync(
                image, email="jane@acme.com", website="https://acme.com"
            )

    assert file_id == "drive-file-1"


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
