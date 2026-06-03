from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.parser import ParsedContact
from app.schemas import ContactRead
from app.scan_flow import process_scan


def test_process_scan_emits_progress_in_order(tmp_path: Path):
    dest = tmp_path / "card.jpg"
    dest.write_bytes(b"\xff\xd8\xff")

    messages: list[str] = []

    async def progress(_stage: str, message: str) -> None:
        messages.append(message)

    db = MagicMock()
    parsed = ParsedContact(name="Ada", email="ada@co.com", phone="+1 555 0100")

    with (
        patch("app.scan_flow.scan_namecard", new_callable=AsyncMock) as mock_ocr,
        patch("app.scan_flow.is_drive_configured", return_value=True),
        patch("app.scan_flow.upload_namecard_copy", new_callable=AsyncMock),
        patch("app.scan_flow.is_notion_configured", return_value=True),
        patch("app.scan_flow.find_existing_contact", return_value=None),
        patch("app.scan_flow.push_contact_safe", return_value=None),
        patch(
            "app.scan_flow.ContactRead.model_validate",
            return_value=ContactRead(
                id=1,
                name="Ada",
                email="ada@co.com",
                created_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
            ),
        ),
    ):
        mock_ocr.return_value = (parsed, "raw", "test")
        asyncio.run(process_scan(dest, db, progress=progress))

    assert messages == [
        "Extracting contact details…",
        "Backing up photo to Google Drive…",
        "Saving to your contacts…",
        "Syncing to Notion…",
    ]
