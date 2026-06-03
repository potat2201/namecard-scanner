from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Contact
from app.parser import ParsedContact

# Fields compared for "already exists" (email matched separately as the key).
COMPARE_FIELDS = ("name", "company", "title", "phone", "website", "address")

_EMAIL_TRAIL = re.compile(r"[.,;:\s]+$")


def normalize_email(email: Optional[str]) -> Optional[str]:
    if email is None:
        return None
    cleaned = email.strip().lower()
    cleaned = _EMAIL_TRAIL.sub("", cleaned)
    return cleaned or None


def scalar_str(value: Any) -> Optional[str]:
    """Coerce OCR/LLM values (lists, numbers) into a single string field."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, list):
        for item in value:
            cleaned = scalar_str(item)
            if cleaned:
                return cleaned
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        text = str(value).strip()
        return text or None
    text = str(value).strip()
    return text or None


def normalize_phone(phone: Any) -> Optional[str]:
    phone = scalar_str(phone)
    if phone is None:
        return None
    digits = re.sub(r"\D", "", phone)
    # Ignore very short fragments (false positives from OCR)
    if len(digits) < 8:
        return None
    return digits


def normalize_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def phones_match(a: Optional[str], b: Optional[str]) -> bool:
    da = normalize_phone(a)
    db = normalize_phone(b)
    return da is not None and da == db


def find_by_email(db: Session, email: str) -> Optional[Contact]:
    normalized = normalize_email(email)
    if not normalized:
        return None
    return (
        db.query(Contact)
        .filter(func.lower(Contact.email) == normalized)
        .first()
    )


def _email_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def find_by_similar_email(db: Session, email: str) -> Optional[Contact]:
    """Catch OCR typos in the local part (e.g. chang-huang vs chang-huong)."""
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        return None
    local, domain = normalized.split("@", 1)
    for contact in db.query(Contact).filter(Contact.email.isnot(None)).all():
        other = normalize_email(contact.email)
        if not other or "@" not in other:
            continue
        other_local, other_domain = other.split("@", 1)
        if other_domain != domain:
            continue
        if other_local == local or _email_similarity(local, other_local) >= 0.88:
            return contact
    return None


def find_by_phone(db: Session, phone: str) -> Optional[Contact]:
    target = normalize_phone(phone)
    if not target:
        return None
    for contact in db.query(Contact).filter(Contact.phone.isnot(None)).all():
        if normalize_phone(contact.phone) == target:
            return contact
    return None


def find_existing_contact(db: Session, parsed: ParsedContact) -> Optional[Contact]:
    """Match by email, similar email (OCR typos), then phone."""
    if parsed.email:
        existing = find_by_email(db, parsed.email)
        if existing:
            return existing
        existing = find_by_similar_email(db, parsed.email)
        if existing:
            return existing
    if parsed.phone:
        existing = find_by_phone(db, parsed.phone)
        if existing:
            return existing
    return None


def fields_unchanged(existing: Contact, parsed: ParsedContact) -> bool:
    for field in COMPARE_FIELDS:
        if field == "phone":
            if normalize_phone(existing.phone) != normalize_phone(parsed.phone):
                return False
        elif normalize_value(getattr(existing, field)) != normalize_value(
            getattr(parsed, field)
        ):
            return False
    return True


def canonicalize_parsed(parsed: ParsedContact) -> ParsedContact:
    """Normalize identifiers before save / duplicate check."""
    return ParsedContact(
        name=scalar_str(parsed.name),
        company=scalar_str(parsed.company),
        title=scalar_str(parsed.title),
        phone=scalar_str(parsed.phone),
        email=normalize_email(scalar_str(parsed.email)),
        website=scalar_str(parsed.website),
        address=scalar_str(parsed.address),
    )


def apply_scan_to_contact(
    contact: Contact,
    parsed: ParsedContact,
    raw_text: str,
    image_path: str,
) -> None:
    parsed = canonicalize_parsed(parsed)
    contact.name = parsed.name
    contact.company = parsed.company
    contact.title = parsed.title
    contact.phone = parsed.phone
    contact.email = parsed.email
    contact.website = parsed.website
    contact.address = parsed.address
    contact.raw_text = raw_text
    contact.image_path = image_path


def replace_contact_image(contact: Contact, new_path: Path) -> None:
    if contact.image_path:
        old = Path(contact.image_path)
        if old.exists() and old.resolve() != new_path.resolve():
            old.unlink()
    contact.image_path = str(new_path)


def discard_uploaded_image(path: Path) -> None:
    if path.exists():
        path.unlink()


def clear_local_database(db: Session) -> dict[str, int]:
    """Remove all contacts and local card images. Does not touch Google Drive."""
    contacts = db.query(Contact).all()
    deleted = len(contacts)
    files_removed = 0

    seen_paths: set[Path] = set()
    for contact in contacts:
        if contact.image_path:
            path = Path(contact.image_path)
            if path not in seen_paths:
                seen_paths.add(path)
                if path.exists():
                    path.unlink()
                    files_removed += 1
        db.delete(contact)

    db.commit()
    return {"deleted": deleted, "files_removed": files_removed}
