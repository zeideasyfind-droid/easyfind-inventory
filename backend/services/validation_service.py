"""Input validation for Module 2 publish requests.

Only file types WhatsApp's Cloud API actually accepts for outbound
image/video messages are allowed through. Per Meta's own documentation
(developers.facebook.com/docs/whatsapp/cloud-api/messages/{image,video}-messages):

  Images: JPEG (image/jpeg), PNG (image/png)      -- max 5 MB each
  Video:  MP4 (video/mp4), 3GPP (video/3gpp)       -- max 16 MB each,
          H.264 video / AAC audio only

WEBP, HEIC/HEIF, MOV and M4V are NOT accepted by WhatsApp for sending --
uploading them to the Media API either fails outright or the resulting
message silently never delivers. Rather than let that fail deep in the
pipeline, they're rejected here with a clear, actionable message so the
broker can convert/re-export before uploading.
"""
from fastapi import UploadFile

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/3gpp"}
ALLOWED_MEDIA_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_VIDEO_BYTES = 16 * 1024 * 1024

# Common unsupported extensions/mime types, mapped to a human hint for the
# error message so the rejection is actionable, not just a bare 415.
_UNSUPPORTED_HINTS = {
    "image/webp": "WEBP images aren't supported by WhatsApp for sending -- please export as JPG or PNG.",
    "image/heic": "HEIC photos aren't supported by WhatsApp for sending -- please export as JPG or PNG.",
    "image/heif": "HEIF photos aren't supported by WhatsApp for sending -- please export as JPG or PNG.",
    "video/quicktime": "MOV videos aren't supported by WhatsApp for sending -- please export as MP4 (H.264/AAC).",
    "video/x-m4v": "M4V videos aren't supported by WhatsApp for sending -- please export as MP4 (H.264/AAC).",
}


class ValidationError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def media_kind(content_type: str) -> str:
    """Returns 'image' or 'video' for an allowed content type."""
    return "image" if content_type in ALLOWED_IMAGE_TYPES else "video"


def validate_publish_request(owner_message: str, images: list[UploadFile]) -> None:
    if not owner_message or not owner_message.strip():
        raise ValidationError(400, "owner_message is required.")

    if not images or all(not (image.filename or "").strip() for image in images):
        raise ValidationError(400, "At least one photo or video is required.")

    for image in images:
        content_type = (image.content_type or "").lower()
        if content_type in ALLOWED_MEDIA_TYPES:
            continue
        hint = _UNSUPPORTED_HINTS.get(content_type)
        if hint:
            raise ValidationError(415, f"{image.filename}: {hint}")
        raise ValidationError(
            415,
            f"Unsupported media type '{content_type or 'unknown'}' for {image.filename}. "
            "Only JPG/PNG photos and MP4/3GP videos are supported.",
        )
