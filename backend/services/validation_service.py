"""Input validation for Module 2 publish requests."""
from fastapi import UploadFile

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


class ValidationError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def validate_publish_request(owner_message: str, images: list[UploadFile]) -> None:
    if not owner_message or not owner_message.strip():
        raise ValidationError(400, "owner_message is required.")

    if not images or all(not (image.filename or "").strip() for image in images):
        raise ValidationError(400, "At least one image is required.")

    for image in images:
        content_type = (image.content_type or "").lower()
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise ValidationError(
                415,
                f"Unsupported image type '{content_type or 'unknown'}' for {image.filename}.",
            )
