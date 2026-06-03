from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import DATA_DIR, UPLOAD_DIR, settings
from app.contacts_service import clear_local_database
from app.database import SessionLocal, get_db, init_db
from app.models import Contact
from app.notion_sync import (
    NotionSyncError,
    archive_contact_in_notion_safe,
    bootstrap_notion_sync,
    clear_notion_database,
    get_sync_status,
    is_notion_configured,
    notion_poll_loop,
    push_contact_safe,
    run_sync,
    touch_updated_at,
)
from app.scan_flow import process_scan, stream_scan_events
from app.schemas import ContactCreate, ContactRead, ContactUpdate, ScanResult

logger = logging.getLogger(__name__)

app = FastAPI(title="Namecard Scanner API", version="1.0.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
_private_lan_origin = (
    r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    r"(:\d+)?"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=_private_lan_origin if settings.lan_expose else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    if settings.notion_sync_enabled and is_notion_configured():
        db = SessionLocal()
        try:
            bootstrap_notion_sync(db)
        except Exception as exc:
            logger.error("Notion bootstrap failed: %s", exc)
        finally:
            db.close()
        asyncio.create_task(notion_poll_loop())


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/ocr-status")
async def ocr_status() -> dict[str, Any]:
    """Check which OCR backends are configured and reachable."""
    status: dict[str, Any] = {
        "tesseract_installed": shutil.which("tesseract") is not None,
        "openai_configured": bool(settings.openai_api_key),
        "ollama": None,
    }

    if settings.ollama_base_url:
        base = settings.ollama_base_url.rstrip("/")
        info: dict[str, Any] = {
            "base_url": base,
            "model": settings.ollama_model,
            "reachable": False,
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{base}/api/tags")
                response.raise_for_status()
                tags = response.json().get("models", [])
                names = [m.get("name", "") for m in tags]
                info["reachable"] = True
                info["installed_models"] = names
                info["vision_model_ready"] = any(
                    settings.ollama_model.split(":")[0] in n for n in names
                ) or any(settings.ollama_model in n for n in names)
        except Exception as exc:
            info["error"] = str(exc)
        status["ollama"] = info

    return status


@app.get("/api/notion-status")
def notion_status() -> dict[str, Any]:
    return get_sync_status()


@app.post("/api/sync/notion")
def sync_notion(
    direction: Literal["both", "push", "pull"] = Query(default="both"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not is_notion_configured():
        raise HTTPException(status_code=400, detail="Notion is not configured")
    return run_sync(db, direction=direction)


@app.get("/api/contacts", response_model=list[ContactRead])
def list_contacts(
    skip: int = 0,
    limit: int = 100,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[Contact]:
    query = db.query(Contact).order_by(Contact.created_at.desc())
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            Contact.name.ilike(pattern)
            | Contact.company.ilike(pattern)
            | Contact.email.ilike(pattern)
            | Contact.phone.ilike(pattern)
        )
    return query.offset(skip).limit(limit).all()


@app.get("/api/contacts/{contact_id}", response_model=ContactRead)
def get_contact(contact_id: int, db: Session = Depends(get_db)) -> Contact:
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@app.post("/api/contacts", response_model=ContactRead, status_code=201)
def create_contact(payload: ContactCreate, db: Session = Depends(get_db)) -> Contact:
    contact = Contact(**payload.model_dump())
    touch_updated_at(contact)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    push_contact_safe(db, contact)
    return contact


@app.patch("/api/contacts/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    db: Session = Depends(get_db),
) -> Contact:
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, key, value)
    touch_updated_at(contact)
    db.commit()
    db.refresh(contact)
    push_contact_safe(db, contact)
    return contact


@app.delete("/api/contacts/{contact_id}", status_code=204, response_class=Response)
def delete_contact(contact_id: int, db: Session = Depends(get_db)) -> Response:
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    archive_contact_in_notion_safe(contact)
    if contact.image_path:
        path = Path(contact.image_path)
        if path.exists():
            path.unlink()
    db.delete(contact)
    db.commit()
    return Response(status_code=204)


@app.delete("/api/contacts")
def clear_contacts(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Clear local contacts and the Notion database rows (if configured).

    Google Drive is not modified.
    """
    notion_result = {"archived": 0, "errors": 0}
    if is_notion_configured():
        try:
            notion_result = clear_notion_database()
        except NotionSyncError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    local_result = clear_local_database(db)
    return {
        **local_result,
        "notion_archived": notion_result["archived"],
        "notion_errors": notion_result["errors"],
    }


def _save_upload(file: UploadFile) -> Path:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    ext = Path(file.filename or "card.jpg").suffix or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / filename

    with dest.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return dest


@app.post("/api/scan", response_model=ScanResult)
async def scan_card(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> ScanResult:
    dest = _save_upload(file)
    return await process_scan(dest, db)


@app.post("/api/scan/stream")
async def scan_card_stream(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    dest = _save_upload(file)
    return StreamingResponse(
        stream_scan_events(dest, db),
        media_type="application/x-ndjson",
    )
