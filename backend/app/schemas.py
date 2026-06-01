from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ContactBase(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None


class ContactCreate(ContactBase):
    raw_text: Optional[str] = None
    image_path: Optional[str] = None


class ContactUpdate(ContactBase):
    pass


class ContactRead(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_text: Optional[str] = None
    image_path: Optional[str] = None
    created_at: datetime


class ScanResult(BaseModel):
    contact: ContactRead
    raw_text: str
    extraction_method: str
    message: str
    sync_warning: Optional[str] = None
