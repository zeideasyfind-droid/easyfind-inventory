"""Request/response models for Module 2 (Property Publishing Engine)."""
from typing import Optional

from pydantic import BaseModel


class PublishPreviewResponse(BaseModel):
    success: bool
    preview: str
    community: str
    society: Optional[str] = None
    landmark: Optional[str] = None
    maps_url: Optional[str] = None


class PublishSendResponse(BaseModel):
    success: bool
    message_id: Optional[str] = None
    image_count: int
    delivery: str
    preview: Optional[str] = None
    error: Optional[str] = None
