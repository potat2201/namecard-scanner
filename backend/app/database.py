from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_CONTACT_SYNC_COLUMNS: dict[str, str] = {
    "notion_page_id": "VARCHAR(36)",
    "updated_at": "DATETIME",
    "notion_last_edited": "DATETIME",
}


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_contacts_table() -> None:
    inspector = inspect(engine)
    if "contacts" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("contacts")}
    added_updated_at = "updated_at" not in existing
    with engine.begin() as conn:
        for name, col_type in _CONTACT_SYNC_COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE contacts ADD COLUMN {name} {col_type}"))

        if added_updated_at:
            conn.execute(
                text(
                    "UPDATE contacts SET updated_at = created_at "
                    "WHERE updated_at IS NULL"
                )
            )


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_contacts_table()
