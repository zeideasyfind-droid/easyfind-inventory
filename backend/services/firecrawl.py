"""Calls the Firecrawl API to scrape a listing URL and use its built-in
LLM extraction to convert the raw page into structured JSON in one call.
"""
import os
from pathlib import Path

import httpx

from backend.config import settings

FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "firecrawl_prompt.txt"

_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "rent": {"type": "number"},
        "deposit": {"type": "number"},
        "maintenance": {"type": "number"},
        "bhk": {"type": "number"},
        "bathrooms": {"type": "number"},
        "balcony": {"type": "number"},
        "furnishing": {"type": "string"},
        "area": {"type": "number"},
        "floor": {"type": "string"},
        "property_type": {"type": "string"},
        "parking": {"type": "string"},
        "tenant_preference": {"type": "string"},
        "pets": {"type": "string"},
        "available_from": {"type": "string"},
        "owner_name": {"type": "string"},
        "contact_number": {"type": "string"},
        "address": {"type": "string"},
        "locality": {"type": "string"},
        "latitude": {"type": "number"},
        "longitude": {"type": "number"},
        "amenities": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
    },
}


class FirecrawlError(Exception):
    pass


def _load_prompt() -> str:
    try:
        text = _PROMPT_PATH.read_text().strip()
    except FileNotFoundError:
        text = ""
    if not text or text.startswith("<PASTE"):
        raise FirecrawlError(
            f"Extraction prompt is not configured. Fill in {_PROMPT_PATH}."
        )
    return text


async def extract_property(url: str) -> dict:
    """Scrape `url` with Firecrawl and return the extracted JSON dict."""
    api_key = settings.FIRECRAWL_API_KEY
    if not api_key:
        raise FirecrawlError("FIRECRAWL_API_KEY is not configured.")

    prompt = _load_prompt()

    payload = {
        "url": url,
        "formats": ["json"],
        "onlyMainContent": True,
        "jsonOptions": {
            "prompt": prompt,
            "schema": _EXTRACTION_SCHEMA,
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(FIRECRAWL_SCRAPE_URL, json=payload, headers=headers)

    if response.status_code >= 400:
        raise FirecrawlError(
            f"Firecrawl request failed ({response.status_code}): {response.text[:500]}"
        )

    body = response.json()
    if not body.get("success", False):
        raise FirecrawlError(f"Firecrawl returned an error: {body}")

    data = body.get("data", {})
    extracted = data.get("json")
    if not extracted:
        raise FirecrawlError("Firecrawl response did not include extracted JSON.")

    return extracted
