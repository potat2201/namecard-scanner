from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import notion_sync
from app.models import Contact


@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    state_path = tmp_path / "notion_sync_state.json"
    monkeypatch.setattr(notion_sync, "SYNC_STATE_PATH", state_path)
    yield


def test_is_notion_configured(monkeypatch):
    monkeypatch.setattr(notion_sync.settings, "notion_token", None)
    monkeypatch.setattr(notion_sync.settings, "notion_parent_page_id", "page-1")
    assert notion_sync.is_notion_configured() is False

    monkeypatch.setattr(notion_sync.settings, "notion_token", "secret")
    assert notion_sync.is_notion_configured() is True


def test_contact_to_notion_properties():
    contact = Contact(
        id=42,
        name="Jane Doe",
        company="Acme",
        title="CEO",
        phone="+1 555-0100",
        email="jane@acme.com",
        website="https://acme.com",
        address="123 Main St",
        raw_text="Jane Doe\nAcme",
        created_at=datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
    )
    props = notion_sync.contact_to_notion_properties(contact)

    assert props["Name"]["title"][0]["text"]["content"] == "Jane Doe"
    assert props["Company"]["rich_text"][0]["text"]["content"] == "Acme"
    assert props["Job Title"]["rich_text"][0]["text"]["content"] == "CEO"
    assert props["Phone"]["phone_number"] == "+1 555-0100"
    assert props["Email"]["email"] == "jane@acme.com"
    assert props["Website"]["url"] == "https://acme.com"
    assert props["App ID"]["number"] == 42
    assert props["Scanned"]["date"]["start"] == "2026-05-31"


def test_page_to_contact_fields():
    page = {
        "id": "page-1",
        "last_edited_time": "2026-05-31T13:00:00.000Z",
        "properties": {
            "Name": {
                "title": [{"plain_text": "Jane Doe", "text": {"content": "Jane Doe"}}],
            },
            "Company": {
                "rich_text": [{"plain_text": "Acme", "text": {"content": "Acme"}}],
            },
            "Job Title": {"rich_text": []},
            "Phone": {"phone_number": "+1 555-0100"},
            "Email": {"email": "jane@acme.com"},
            "Website": {"url": "https://acme.com"},
            "Address": {"rich_text": []},
            "Raw OCR": {"rich_text": []},
            "App ID": {"number": 7},
        },
    }
    fields = notion_sync._page_to_contact_fields(page)
    assert fields["name"] == "Jane Doe"
    assert fields["company"] == "Acme"
    assert fields["email"] == "jane@acme.com"
    assert fields["app_id"] == 7


def test_notion_is_newer():
    contact = Contact(
        id=1,
        updated_at=datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
    )
    page = {"last_edited_time": "2026-05-31T13:00:00.000Z"}
    assert notion_sync._notion_is_newer(contact, page) is True

    contact.updated_at = datetime(2026, 5, 31, 14, 0, tzinfo=timezone.utc)
    assert notion_sync._notion_is_newer(contact, page) is False


def test_push_contact_creates_page(monkeypatch):
    monkeypatch.setattr(notion_sync.settings, "notion_token", "secret")
    monkeypatch.setattr(notion_sync.settings, "notion_parent_page_id", "parent-1")
    monkeypatch.setattr(notion_sync.settings, "notion_database_id", "db-1")

    contact = Contact(
        id=5,
        name="Jane Doe",
        created_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )

    mock_client = MagicMock()
    mock_client.pages.create.return_value = {
        "id": "new-page",
        "last_edited_time": "2026-05-31T13:00:00.000Z",
    }

    db = MagicMock()
    with patch.object(notion_sync, "_get_client", return_value=mock_client):
        notion_sync.push_contact(db, contact)

    assert contact.notion_page_id == "new-page"
    mock_client.pages.create.assert_called_once()
    db.commit.assert_called_once()


def test_pull_archived_page_deletes_local_contact(monkeypatch):
    monkeypatch.setattr(notion_sync.settings, "notion_token", "secret")
    monkeypatch.setattr(notion_sync.settings, "notion_parent_page_id", "parent-1")
    monkeypatch.setattr(notion_sync.settings, "notion_database_id", "db-1")

    contact = Contact(id=1, notion_page_id="page-1")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = contact

    page = {
        "id": "page-1",
        "archived": True,
        "last_edited_time": "2026-05-31T13:00:00.000Z",
        "properties": {},
    }

    mock_client = MagicMock()
    mock_client.request.return_value = {
        "results": [page],
        "has_more": False,
    }

    with patch.object(notion_sync, "_get_client", return_value=mock_client):
        result = notion_sync.pull_from_notion(db)

    assert result["deleted"] == 1
    db.delete.assert_called_once_with(contact)


def test_clear_notion_database_archives_active_pages(monkeypatch):
    monkeypatch.setattr(notion_sync.settings, "notion_token", "secret")
    monkeypatch.setattr(notion_sync.settings, "notion_parent_page_id", "parent-1")
    monkeypatch.setattr(notion_sync.settings, "notion_database_id", "db-1")

    mock_client = MagicMock()
    mock_client.request.return_value = {
        "results": [
            {"id": "page-a", "archived": False},
            {"id": "page-b", "archived": True},
        ],
        "has_more": False,
    }

    with patch.object(notion_sync, "_get_client", return_value=mock_client):
        result = notion_sync.clear_notion_database()

    assert result == {"archived": 1, "errors": 0}
    mock_client.pages.update.assert_called_once_with(
        page_id="page-a",
        archived=True,
    )
