"""Uploads property images to Cloudinary and returns a 1080×1080
cropped, optimised secure URL for use in Meta Commerce Catalog.

Uses Cloudinary's REST upload API directly (no SDK dependency).
Signature scheme: Cloudinary V1 (SHA-1 over sorted param string + secret).
"""
import hashlib
import logging
import time

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

_UPLOAD_BASE = "https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
_TRANSFORMATION = "c_fill,h_1080,w_1080"
_FOLDER = "easyfind"


class CloudinaryError(Exception):
    pass


def _sign(params: dict, api_secret: str) -> str:
    """Cloudinary V1 HMAC-less signature: SHA-1(sorted_params + secret)."""
    # Exclude keys that are never signed.
    skip = {"file", "api_key", "resource_type", "cloud_name"}
    sorted_items = sorted((k, v) for k, v in params.items() if k not in skip)
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    return hashlib.sha1(f"{param_str}{api_secret}".encode()).hexdigest()


async def upload_and_transform(image_url: str) -> str:
    """Upload *image_url* to Cloudinary, apply a 1080×1080 fill crop, and
    return the resulting secure delivery URL.

    The image is stored under the ``easyfind/`` folder so catalog images
    are grouped and easy to audit in the Cloudinary dashboard.
    """
    cloud_name = settings.CLOUDINARY_CLOUD_NAME
    api_key = settings.CLOUDINARY_API_KEY
    api_secret = settings.CLOUDINARY_API_SECRET

    if not all([cloud_name, api_key, api_secret]):
        raise CloudinaryError(
            "Cloudinary credentials are not fully configured "
            "(CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET)."
        )

    timestamp = int(time.time())

    # Params to sign (file is passed but not signed).
    sign_params: dict = {
        "folder": _FOLDER,
        "timestamp": timestamp,
        "transformation": _TRANSFORMATION,
    }
    signature = _sign(sign_params, api_secret)

    form_data = {
        "file": image_url,
        "api_key": api_key,
        "timestamp": str(timestamp),
        "folder": _FOLDER,
        "transformation": _TRANSFORMATION,
        "signature": signature,
    }

    upload_url = _UPLOAD_BASE.format(cloud_name=cloud_name)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(upload_url, data=form_data)

    if response.status_code >= 400:
        raise CloudinaryError(
            f"Cloudinary upload failed ({response.status_code}): "
            f"{response.text[:500]}"
        )

    body = response.json()
    if "error" in body:
        msg = body["error"].get("message", str(body["error"]))
        raise CloudinaryError(f"Cloudinary error: {msg}")

    secure_url = body.get("secure_url", "")
    if not secure_url:
        raise CloudinaryError("Cloudinary response is missing 'secure_url'.")

    logger.info(
        "Cloudinary upload OK — public_id=%s url=%s",
        body.get("public_id"),
        secure_url,
    )
    return secure_url


def extract_og_image(raw_response: dict) -> str | None:
    """Pull the best available image URL out of a Firecrawl raw response.

    Firecrawl stores page metadata under ``data.metadata``; OG images,
    Twitter cards, and plain ``image`` keys are all tried in order.
    Returns ``None`` if nothing usable is found.
    """
    data = (raw_response or {}).get("data") or {}
    metadata = data.get("metadata") or {}

    for key in ("ogImage", "og:image", "twitterImage", "twitter:image", "image"):
        value = metadata.get(key)
        if value and isinstance(value, str) and value.startswith("http"):
            return value

    return None
