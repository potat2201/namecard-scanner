from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.contacts_service import (
    apply_scan_to_contact,
    canonicalize_parsed,
    discard_uploaded_image,
    fields_unchanged,
    find_existing_contact,
    replace_contact_image,
)
from app.google_drive import GoogleDriveError, is_drive_configured, upload_namecard_copy
from app.models import Contact
from app.notion_sync import is_notion_configured, push_contact_safe, touch_updated_at
from app.ocr import scan_namecard
from app.schemas import ContactRead, ScanResult

ProgressFn = Callable[[str, str], Awaitable[None]]


async def _emit(progress: Optional[ProgressFn], stage: str, message: str) -> None:
    if progress is not None:
        await progress(stage, message)


async def process_scan(
    dest: Path,
    db: Session,
    *,
    progress: Optional[ProgressFn] = None,
) -> ScanResult:
    """Run OCR, optional Drive backup, DB save, and optional Notion push."""
    await _emit(progress, "ocr", "Extracting contact details…")
    try:
        parsed, raw_text, method = await scan_namecard(dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail=f"Could not read name card: {exc}",
        ) from exc

    parsed = canonicalize_parsed(parsed)

    if is_drive_configured():
        await _emit(progress, "drive", "Backing up photo to Google Drive…")
        try:
            await upload_namecard_copy(
                dest, email=parsed.email, company=parsed.company
            )
        except GoogleDriveError as exc:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    await _emit(progress, "database", "Saving to your contacts…")

    message = "Contact created"
    dest_str = str(dest)
    sync_warning: Optional[str] = None

    existing = find_existing_contact(db, parsed)
    if existing:
        if fields_unchanged(existing, parsed):
            discard_uploaded_image(dest)
            db.refresh(existing)
            return ScanResult(
                contact=ContactRead.model_validate(existing),
                raw_text=raw_text,
                extraction_method=method,
                message="Contact Already Exists",
            )

        apply_scan_to_contact(existing, parsed, raw_text, dest_str)
        replace_contact_image(existing, dest)
        touch_updated_at(existing)
        db.commit()
        db.refresh(existing)
        if is_notion_configured():
            await _emit(progress, "notion", "Syncing to Notion…")
        sync_warning = push_contact_safe(db, existing)
        return ScanResult(
            contact=ContactRead.model_validate(existing),
            raw_text=raw_text,
            extraction_method=method,
            message="Contact updated",
            sync_warning=sync_warning,
        )

    contact = Contact(
        name=parsed.name,
        company=parsed.company,
        title=parsed.title,
        phone=parsed.phone,
        email=parsed.email,
        website=parsed.website,
        address=parsed.address,
        raw_text=raw_text,
        image_path=dest_str,
    )
    touch_updated_at(contact)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    if is_notion_configured():
        await _emit(progress, "notion", "Syncing to Notion…")
    sync_warning = push_contact_safe(db, contact)

    return ScanResult(
        contact=ContactRead.model_validate(contact),
        raw_text=raw_text,
        extraction_method=method,
        message=message,
        sync_warning=sync_warning,
    )


async def stream_scan_events(dest: Path, db: Session) -> AsyncIterator[str]:
    """NDJSON: progress events, then one complete or error line."""
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    async def progress(stage: str, message: str) -> None:
        await queue.put(
            json.dumps({"type": "progress", "stage": stage, "message": message}) + "\n"
        )

    async def run() -> None:
        try:
            await queue.put(
                json.dumps(
                    {"type": "progress", "stage": "saving", "message": "Saving photo…"}
                )
                + "\n"
            )
            result = await process_scan(dest, db, progress=progress)
            await queue.put(
                json.dumps(
                    {"type": "complete", "result": result.model_dump(mode="json")}
                )
                + "\n"
            )
        except HTTPException as exc:
            dest.unlink(missing_ok=True)
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            await queue.put(
                json.dumps(
                    {"type": "error", "detail": detail, "status": exc.status_code}
                )
                + "\n"
            )
        except Exception as exc:
            dest.unlink(missing_ok=True)
            await queue.put(
                json.dumps({"type": "error", "detail": str(exc), "status": 500}) + "\n"
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())
    try:
        while True:
            line = await queue.get()
            if line is None:
                break
            yield line
    finally:
        await task
