from __future__ import annotations

import json
import re
from dataclasses import dataclass

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}(?:[\s.-]?\d{1,4})?"
)
URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s]*)?",
    re.IGNORECASE,
)
TITLE_KEYWORDS = re.compile(
    r"\b(CEO|CTO|CFO|COO|CMO|Director|Manager|Engineer|Developer|"
    r"President|Vice President|VP|Founder|Consultant|Analyst|Lead|"
    r"Head of|Chief|Officer|Specialist|Coordinator|Associate)\b",
    re.IGNORECASE,
)


@dataclass
class ParsedContact:
    name: str | None = None
    company: str | None = None
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    address: str | None = None


def _normalize_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines


def _normalize_email_raw(email: str) -> str:
    return email.strip().lower().rstrip(".,;:")


def _pick_email(text: str) -> str | None:
    matches = EMAIL_RE.findall(text)
    if not matches:
        return None
    normalized = [_normalize_email_raw(m) for m in matches]
    # Prefer the longest address — usually the full corporate email on a card.
    return max(normalized, key=len)


def _pick_phones(text: str) -> list[str]:
    phones: list[str] = []
    for match in PHONE_RE.finditer(text):
        candidate = re.sub(r"\s+", " ", match.group(0).strip())
        digits = re.sub(r"\D", "", candidate)
        if len(digits) >= 7:
            phones.append(candidate)
    return list(dict.fromkeys(phones))


def _pick_website(text: str, email: str | None) -> str | None:
    for match in URL_RE.finditer(text):
        url = match.group(0)
        if email and url.lower() in email.lower():
            continue
        if "@" in url:
            continue
        return url if url.startswith("http") else f"https://{url}"
    if email:
        domain = email.split("@", 1)[1]
        if domain and "." in domain:
            return f"https://{domain}"
    return None


def _pick_title(lines: list[str]) -> str | None:
    for line in lines:
        if TITLE_KEYWORDS.search(line) and not EMAIL_RE.search(line):
            return line
    return None


def _pick_name(lines: list[str], email: str | None, phone: str | None) -> str | None:
    skip = {email, phone} if email or phone else set()
    for line in lines[:4]:
        if line in skip:
            continue
        if EMAIL_RE.search(line) or PHONE_RE.fullmatch(line.replace(" ", "")):
            continue
        if URL_RE.search(line) and len(line) < 40:
            continue
        if len(line.split()) <= 5 and not line.isupper():
            return line
        if len(line.split()) <= 4:
            return line
    for line in lines:
        if line not in skip and not EMAIL_RE.search(line) and len(line) < 50:
            words = line.split()
            if 1 <= len(words) <= 4:
                return line
    return lines[0] if lines else None


def _pick_company(lines: list[str], name: str | None, title: str | None) -> str | None:
    used = {name, title}
    for line in lines:
        if line in used or not line:
            continue
        if EMAIL_RE.search(line) or PHONE_RE.search(line):
            continue
        if TITLE_KEYWORDS.search(line) and line == title:
            continue
        if len(line) > 3:
            return line
    return None


def _pick_address(lines: list[str], used: set[str | None]) -> str | None:
    address_lines: list[str] = []
    for line in lines:
        if line in used:
            continue
        if re.search(r"\d+.*(?:street|st\.|road|rd\.|ave|avenue|blvd|suite|floor|hk|hong kong)", line, re.I):
            address_lines.append(line)
        elif re.search(r"\b\d{3,5}\b", line) and len(line) > 15:
            address_lines.append(line)
    return ", ".join(address_lines) if address_lines else None


def parse_contact_text(text: str) -> ParsedContact:
    lines = _normalize_lines(text)
    full = "\n".join(lines)

    email = _pick_email(full)
    phones = _pick_phones(full)
    phone = phones[0] if phones else None
    website = _pick_website(full, email)
    title = _pick_title(lines)
    name = _pick_name(lines, email, phone)
    company = _pick_company(lines, name, title)
    address = _pick_address(lines, {name, company, title, email, phone, website})

    return ParsedContact(
        name=name,
        company=company,
        title=title,
        phone=phone,
        email=email,
        website=website,
        address=address,
    )


def _llm_field(data: dict, key: str) -> str | None:
    from app.contacts_service import scalar_str

    return scalar_str(data.get(key))


def parse_llm_json(content: str) -> ParsedContact:
    data = json.loads(content)
    return ParsedContact(
        name=_llm_field(data, "name"),
        company=_llm_field(data, "company"),
        title=_llm_field(data, "title"),
        phone=_llm_field(data, "phone"),
        email=_llm_field(data, "email"),
        website=_llm_field(data, "website"),
        address=_llm_field(data, "address"),
    )
