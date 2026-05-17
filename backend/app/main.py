from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import DATA_DIR, UPLOAD_DIR, settings
from app.contacts_service import (
    apply_scan_to_contact,
    canonicalize_parsed,
    discard_uploaded_image,
    fields_unchanged,
    find_existing_contact,
    replace_contact_image,
)
from app.database import get_db, init_db
from app.models import Contact
from app.ocr import scan_namecard
from app.schemas import ContactCreate, ContactRead, ContactUpdate, ScanResult

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
def on_startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    init_db()


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
    db.add(contact)
    db.commit()
    db.refresh(contact)
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
    db.commit()
    db.refresh(contact)
    return contact


@app.delete("/api/contacts/{contact_id}", status_code=204, response_class=Response)
def delete_contact(contact_id: int, db: Session = Depends(get_db)) -> Response:
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if contact.image_path:
        path = Path(contact.image_path)
        if path.exists():
            path.unlink()
    db.delete(contact)
    db.commit()
    return Response(status_code=204)


@app.post("/api/scan", response_model=ScanResult)
async def scan_card(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> ScanResult:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    ext = Path(file.filename or "card.jpg").suffix or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / filename

    with dest.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        parsed, raw_text, method = await scan_namecard(dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail=f"Could not read name card: {exc}",
        ) from exc

    parsed = canonicalize_parsed(parsed)
    message = "Contact created"
    dest_str = str(dest)

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
        db.commit()
        db.refresh(existing)
        return ScanResult(
            contact=ContactRead.model_validate(existing),
            raw_text=raw_text,
            extraction_method=method,
            message="Contact updated",
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
    db.add(contact)
    db.commit()
    db.refresh(contact)

    return ScanResult(
        contact=ContactRead.model_validate(contact),
        raw_text=raw_text,
        extraction_method=method,
        message=message,
    )
