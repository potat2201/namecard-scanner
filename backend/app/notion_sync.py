from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from notion_client import Client
from notion_client.errors import APIResponseError
from sqlalchemy.orm import Session

from app.config import DATA_DIR, settings
from app.contacts_service import find_by_email, find_by_phone, normalize_email, normalize_phone
from app.database import SessionLocal
from app.models import Contact

logger = logging.getLogger(__name__)

SYNC_STATE_PATH = DATA_DIR / "notion_sync_state.json"
DATABASE_TITLE = "Namecard Contacts"
NOTION_API_VERSION = "2022-06-28"

DATABASE_PROPERTIES: dict[str, dict[str, Any]] = {
    "Name": {"title": {}},
    "Company": {"rich_text": {}},
    "Job Title": {"rich_text": {}},
    "Phone": {"phone_number": {}},
    "Email": {"email": {}},
    "Website": {"url": {}},
    "Address": {"rich_text": {}},
    "Raw OCR": {"rich_text": {}},
    "App ID": {"number": {}},
    "Scanned": {"date": {}},
}

_PROP_NAME = "Name"
_PROP_COMPANY = "Company"
_PROP_JOB_TITLE = "Job Title"
_PROP_PHONE = "Phone"
_PROP_EMAIL = "Email"
_PROP_WEBSITE = "Website"
_PROP_ADDRESS = "Address"
_PROP_RAW_OCR = "Raw OCR"
_PROP_APP_ID = "App ID"
_PROP_SCANNED = "Scanned"


class NotionSyncError(Exception):
    """Raised when Notion sync operations fail."""


def is_notion_configured() -> bool:
    return bool(settings.notion_token and settings.notion_parent_page_id)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_notion_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_date_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def _rich_text(value: Optional[str]) -> dict[str, Any]:
    if not value:
        return {"rich_text": []}
    return {
        "rich_text": [{"type": "text", "text": {"content": value[:2000]}}],
    }


def _title(value: Optional[str]) -> dict[str, Any]:
    content = (value or "Unknown").strip() or "Unknown"
    return {
        "title": [{"type": "text", "text": {"content": content[:2000]}}],
    }


def _load_state() -> dict[str, Any]:
    if not SYNC_STATE_PATH.exists():
        return {}
    try:
        return json.loads(SYNC_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_sync_status() -> dict[str, Any]:
    state = _load_state()
    return {
        "configured": is_notion_configured(),
        "enabled": settings.notion_sync_enabled,
        "database_id": settings.notion_database_id or state.get("database_id"),
        "last_pull_at": state.get("last_pull_at"),
        "last_push_at": state.get("last_push_at"),
        "last_error": state.get("last_error"),
    }


def _get_client() -> Client:
    if not settings.notion_token:
        raise NotionSyncError("NOTION_TOKEN is not configured")
    return Client(auth=settings.notion_token, notion_version=NOTION_API_VERSION)


def _find_child_database(client: Client, parent_page_id: str) -> Optional[str]:
    cursor: Optional[str] = None
    while True:
        response = client.blocks.children.list(block_id=parent_page_id, start_cursor=cursor)
        for block in response.get("results", []):
            if block.get("type") != "child_database":
                continue
            title_parts = block.get("child_database", {}).get("title", "")
            title = title_parts if isinstance(title_parts, str) else ""
            if title == DATABASE_TITLE:
                return block["id"]
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return None


def _ensure_database_schema(client: Client, database_id: str) -> None:
    database = client.databases.retrieve(database_id=database_id)
    existing = set(database.get("properties", {}).keys())
    missing = {
        name: schema
        for name, schema in DATABASE_PROPERTIES.items()
        if name not in existing
    }
    if not missing:
        return

    client.databases.update(database_id=database_id, properties=missing)
    logger.info("Added Notion database properties: %s", ", ".join(missing.keys()))


def _resolve_database_id(client: Client) -> str:
    if settings.notion_database_id:
        database_id = settings.notion_database_id
        _ensure_database_schema(client, database_id)
        return database_id

    state = _load_state()
    if state.get("database_id"):
        database_id = state["database_id"]
        _ensure_database_schema(client, database_id)
        return database_id

    if not settings.notion_parent_page_id:
        raise NotionSyncError("NOTION_PARENT_PAGE_ID is not configured")

    existing_id = _find_child_database(client, settings.notion_parent_page_id)
    if existing_id:
        state["database_id"] = existing_id
        _save_state(state)
        _ensure_database_schema(client, existing_id)
        logger.info("Using existing Notion database id=%s", existing_id)
        return existing_id

    created = client.databases.create(
        parent={"type": "page_id", "page_id": settings.notion_parent_page_id},
        title=[{"type": "text", "text": {"content": DATABASE_TITLE}}],
        properties=DATABASE_PROPERTIES,
    )
    database_id = created["id"]
    _ensure_database_schema(client, database_id)
    state["database_id"] = database_id
    state.pop("last_error", None)
    _save_state(state)
    logger.info(
        "Created Notion database '%s' with id=%s — add NOTION_DATABASE_ID=%s to .env",
        DATABASE_TITLE,
        database_id,
        database_id,
    )
    return database_id


def contact_to_notion_properties(contact: Contact) -> dict[str, Any]:
    props: dict[str, Any] = {
        _PROP_NAME: _title(contact.name),
        _PROP_COMPANY: _rich_text(contact.company),
        _PROP_JOB_TITLE: _rich_text(contact.title),
        _PROP_ADDRESS: _rich_text(contact.address),
        _PROP_RAW_OCR: _rich_text(contact.raw_text),
        _PROP_APP_ID: {"number": contact.id},
        _PROP_SCANNED: {"date": {"start": _to_date_str(contact.created_at)}},
    }

    if contact.phone:
        props[_PROP_PHONE] = {"phone_number": contact.phone[:200]}
    else:
        props[_PROP_PHONE] = {"phone_number": None}

    if contact.email:
        props[_PROP_EMAIL] = {"email": contact.email}
    else:
        props[_PROP_EMAIL] = {"email": None}

    if contact.website:
        props[_PROP_WEBSITE] = {"url": contact.website[:2000]}
    else:
        props[_PROP_WEBSITE] = {"url": None}

    return props


def _plain_text(prop: dict[str, Any]) -> Optional[str]:
    rich = prop.get("rich_text") or prop.get("title") or []
    parts = [item.get("plain_text", "") for item in rich if isinstance(item, dict)]
    joined = "".join(parts).strip()
    return joined or None


def _page_to_contact_fields(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("properties", {})
    name = _plain_text(props.get(_PROP_NAME, {}))
    company = _plain_text(props.get(_PROP_COMPANY, {}))
    title = _plain_text(props.get(_PROP_JOB_TITLE, {}))
    address = _plain_text(props.get(_PROP_ADDRESS, {}))
    raw_text = _plain_text(props.get(_PROP_RAW_OCR, {}))

    phone_prop = props.get(_PROP_PHONE, {})
    phone = phone_prop.get("phone_number") if isinstance(phone_prop, dict) else None

    email_prop = props.get(_PROP_EMAIL, {})
    email = email_prop.get("email") if isinstance(email_prop, dict) else None

    website_prop = props.get(_PROP_WEBSITE, {})
    website = website_prop.get("url") if isinstance(website_prop, dict) else None

    app_id_prop = props.get(_PROP_APP_ID, {})
    app_id = app_id_prop.get("number") if isinstance(app_id_prop, dict) else None

    return {
        "name": name,
        "company": company,
        "title": title,
        "phone": phone,
        "email": normalize_email(email),
        "website": website,
        "address": address,
        "raw_text": raw_text,
        "app_id": app_id,
    }


def touch_updated_at(contact: Contact) -> None:
    contact.updated_at = _utcnow()


def _find_contact_for_page(db: Session, page: dict[str, Any]) -> Optional[Contact]:
    page_id = page.get("id")
    if page_id:
        by_page = db.query(Contact).filter(Contact.notion_page_id == page_id).first()
        if by_page:
            return by_page

    fields = _page_to_contact_fields(page)
    app_id = fields.get("app_id")
    if app_id is not None:
        by_id = db.get(Contact, int(app_id))
        if by_id:
            return by_id

    email = fields.get("email")
    if email:
        by_email = find_by_email(db, email)
        if by_email:
            return by_email

    phone = fields.get("phone")
    if phone:
        by_phone = find_by_phone(db, phone)
        if by_phone:
            return by_phone

    return None


def _notion_is_newer(contact: Contact, page: dict[str, Any]) -> bool:
    notion_edited = _parse_notion_time(page["last_edited_time"])
    local_updated = contact.updated_at
    if local_updated.tzinfo is None:
        local_updated = local_updated.replace(tzinfo=timezone.utc)
    return notion_edited > local_updated


def _apply_page_to_contact(contact: Contact, page: dict[str, Any]) -> None:
    fields = _page_to_contact_fields(page)
    contact.name = fields["name"]
    contact.company = fields["company"]
    contact.title = fields["title"]
    contact.phone = fields["phone"]
    contact.email = fields["email"]
    contact.website = fields["website"]
    contact.address = fields["address"]
    contact.raw_text = fields["raw_text"]
    contact.notion_page_id = page["id"]
    notion_edited = _parse_notion_time(page["last_edited_time"])
    contact.notion_last_edited = notion_edited
    contact.updated_at = notion_edited


def push_contact(db: Session, contact: Contact) -> None:
    if not is_notion_configured():
        return

    client = _get_client()
    database_id = _resolve_database_id(client)
    properties = contact_to_notion_properties(contact)

    try:
        if contact.notion_page_id:
            page = client.pages.update(
                page_id=contact.notion_page_id,
                properties=properties,
            )
        else:
            page = client.pages.create(
                parent={"database_id": database_id},
                properties=properties,
            )
            contact.notion_page_id = page["id"]

        contact.notion_last_edited = _parse_notion_time(page["last_edited_time"])
        db.commit()

        state = _load_state()
        state["last_push_at"] = _utcnow().isoformat()
        state.pop("last_error", None)
        _save_state(state)
    except APIResponseError as exc:
        raise NotionSyncError(str(exc)) from exc


def push_contact_safe(db: Session, contact: Contact) -> Optional[str]:
    try:
        push_contact(db, contact)
        return None
    except NotionSyncError as exc:
        logger.warning("Notion push failed for contact %s: %s", contact.id, exc)
        state = _load_state()
        state["last_error"] = str(exc)
        _save_state(state)
        return str(exc)


def archive_contact_in_notion(contact: Contact) -> None:
    if not is_notion_configured() or not contact.notion_page_id:
        return

    client = _get_client()
    try:
        client.pages.update(page_id=contact.notion_page_id, archived=True)
    except APIResponseError as exc:
        raise NotionSyncError(str(exc)) from exc


def archive_contact_in_notion_safe(contact: Contact) -> Optional[str]:
    try:
        archive_contact_in_notion(contact)
        return None
    except NotionSyncError as exc:
        logger.warning("Notion archive failed for contact %s: %s", contact.id, exc)
        return str(exc)


def push_all_contacts(db: Session) -> dict[str, int]:
    if not is_notion_configured():
        return {"pushed": 0, "errors": 0}

    pushed = 0
    errors = 0
    contacts = db.query(Contact).order_by(Contact.id).all()
    for contact in contacts:
        if push_contact_safe(db, contact):
            errors += 1
        else:
            pushed += 1
    return {"pushed": pushed, "errors": errors}


def pull_from_notion(db: Session) -> dict[str, int]:
    if not is_notion_configured():
        return {"updated": 0, "deleted": 0, "skipped": 0, "errors": 0}

    client = _get_client()
    database_id = _resolve_database_id(client)

    updated = 0
    deleted = 0
    skipped = 0
    errors = 0
    cursor: Optional[str] = None

    while True:
        try:
            response = client.databases.query(
                database_id=database_id,
                start_cursor=cursor,
                page_size=100,
            )
        except APIResponseError as exc:
            state = _load_state()
            state["last_error"] = str(exc)
            _save_state(state)
            raise NotionSyncError(str(exc)) from exc

        for page in response.get("results", []):
            try:
                if page.get("archived"):
                    contact = _find_contact_for_page(db, page)
                    if contact:
                        if contact.image_path:
                            image = Path(contact.image_path)
                            if image.exists():
                                image.unlink()
                        db.delete(contact)
                        deleted += 1
                    continue

                contact = _find_contact_for_page(db, page)
                if contact is None:
                    fields = _page_to_contact_fields(page)
                    notion_edited = _parse_notion_time(page["last_edited_time"])
                    contact = Contact(
                        name=fields["name"],
                        company=fields["company"],
                        title=fields["title"],
                        phone=fields["phone"],
                        email=fields["email"],
                        website=fields["website"],
                        address=fields["address"],
                        raw_text=fields["raw_text"],
                        notion_page_id=page["id"],
                        notion_last_edited=notion_edited,
                        updated_at=notion_edited,
                    )
                    db.add(contact)
                    updated += 1
                    continue

                if not _notion_is_newer(contact, page):
                    skipped += 1
                    continue

                _apply_page_to_contact(contact, page)
                updated += 1
            except Exception as exc:
                logger.exception("Failed to pull Notion page %s", page.get("id"))
                errors += 1
                state = _load_state()
                state["last_error"] = str(exc)
                _save_state(state)

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    db.commit()
    state = _load_state()
    state["last_pull_at"] = _utcnow().isoformat()
    state.pop("last_error", None)
    _save_state(state)
    return {
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
        "errors": errors,
    }


def run_sync(db: Session, direction: str = "both") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if direction in ("both", "push"):
        result["push"] = push_all_contacts(db)
    if direction in ("both", "pull"):
        result["pull"] = pull_from_notion(db)
    return result


def bootstrap_notion_sync(db: Session) -> None:
    if not is_notion_configured() or not settings.notion_sync_enabled:
        return
    try:
        client = _get_client()
        _resolve_database_id(client)
        push_all_contacts(db)
    except Exception as exc:
        state = _load_state()
        state["last_error"] = str(exc)
        _save_state(state)
        raise


async def notion_poll_loop() -> None:
    while True:
        await asyncio.sleep(settings.notion_sync_poll_seconds)
        if not settings.notion_sync_enabled or not is_notion_configured():
            continue
        db = SessionLocal()
        try:
            await asyncio.to_thread(pull_from_notion, db)
        except Exception as exc:
            logger.exception("Notion pull failed: %s", exc)
            state = _load_state()
            state["last_error"] = str(exc)
            _save_state(state)
        finally:
            db.close()
