from __future__ import annotations

from app.contacts_service import (
    fields_unchanged,
    find_by_phone,
    normalize_email,
    normalize_phone,
    phones_match,
)
from app.models import Contact
from app.parser import ParsedContact


def test_normalize_email():
    assert normalize_email("  John@Example.COM ") == "john@example.com"
    assert normalize_email("") is None
    assert normalize_email(None) is None


def test_fields_unchanged():
    existing = Contact(
        name="Jane Doe",
        company="Acme",
        title="CEO",
        phone="+1 555",
        email="jane@acme.com",
        website="https://acme.com",
        address="123 Main St",
    )
    parsed = ParsedContact(
        name="Jane Doe",
        company="Acme",
        title="CEO",
        phone="+1 555",
        email="jane@acme.com",
        website="https://acme.com",
        address="123 Main St",
    )
    assert fields_unchanged(existing, parsed) is True

    parsed.title = "CTO"
    assert fields_unchanged(existing, parsed) is False


def test_normalize_phone_and_match():
    assert normalize_phone("M 852 5560 2741") == "85255602741"
    assert phones_match("+65 8128 2399", "+65 6128 2399") is False
    assert phones_match("M 852 5560 2741", "852-5560-2741") is True


def test_email_normalization_strips_punctuation():
    assert normalize_email("User@Example.COM.") == "user@example.com"
