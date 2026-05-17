from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageEnhance, ImageOps

from app.config import settings
from app.parser import ParsedContact, parse_contact_text, parse_llm_json

try:
    import pytesseract
except ImportError:
    pytesseract = None  # type: ignore[assignment]

EXTRACTION_PROMPT = (
    "Extract business card fields from this image. "
    "Return ONLY valid JSON with keys: name, company, title, phone, email, website, address. "
    "Use null for missing fields. No markdown, no explanation."
)


def preprocess_image(image: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(image)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.4)
    img = ImageEnhance.Sharpness(img).enhance(1.2)
    return img


def _strip_markdown_json(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    match = re.search(r"\{[\s\S]*\}", content)
    return match.group(0) if match else content


def _parse_llm_response(content: str) -> tuple[ParsedContact, str]:
    cleaned = _strip_markdown_json(content)
    try:
        parsed = parse_llm_json(cleaned)
    except (json.JSONDecodeError, TypeError):
        parsed = parse_contact_text(content)
    return parsed, content


def extract_text_tesseract(image: Image.Image) -> str:
    if pytesseract is None:
        raise RuntimeError("pytesseract is not installed")
    processed = preprocess_image(image)
    text = pytesseract.image_to_string(processed, lang="eng+chi_tra+chi_sim")
    return text.strip()


async def extract_with_ollama(image_bytes: bytes) -> tuple[ParsedContact, str]:
    if not settings.ollama_base_url:
        raise RuntimeError("OLLAMA_BASE_URL is not set")

    base = settings.ollama_base_url.rstrip("/")
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
        response = await client.post(
            f"{base}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": [
                    {
                        "role": "user",
                        "content": EXTRACTION_PROMPT,
                        "images": [b64],
                    }
                ],
                "stream": False,
            },
        )
        response.raise_for_status()
        payload = response.json()

    content = payload.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("Ollama returned an empty response")

    return _parse_llm_response(content)


async def extract_with_openai(image_bytes: bytes) -> tuple[ParsedContact, str]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.openai_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": EXTRACTION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                        ],
                    }
                ],
                "max_tokens": 500,
            },
        )
        response.raise_for_status()
        payload = response.json()

    content = payload["choices"][0]["message"]["content"].strip()
    return _parse_llm_response(content)


async def scan_namecard(image_path: Path) -> tuple[ParsedContact, str, str]:
    """Returns (parsed fields, raw text, extraction method)."""
    image_bytes = image_path.read_bytes()
    image = Image.open(BytesIO(image_bytes))
    errors: list[str] = []

    if settings.ollama_base_url:
        try:
            parsed, raw = await extract_with_ollama(image_bytes)
            return parsed, raw, f"ollama:{settings.ollama_model}"
        except Exception as exc:
            errors.append(f"Ollama ({settings.ollama_base_url}): {exc}")

    if settings.openai_api_key:
        try:
            parsed, raw = await extract_with_openai(image_bytes)
            return parsed, raw, "openai-vision"
        except Exception as exc:
            errors.append(f"OpenAI: {exc}")

    try:
        raw_text = extract_text_tesseract(image)
        parsed = parse_contact_text(raw_text)
        return parsed, raw_text, "tesseract"
    except Exception as exc:
        errors.append(f"Tesseract: {exc}")

    hint = (
        "Configure OLLAMA_BASE_URL in .env (vision model required, e.g. llava), "
        "set OPENAI_API_KEY, or install Tesseract."
    )
    raise RuntimeError(f"{'; '.join(errors)}. {hint}")
