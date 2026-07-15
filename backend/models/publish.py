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
    request_id: Optional[str] = None


class WhatsAppStatusVar(BaseModel):
    """Per-variable status in the /publish/status response."""
    present: bool
    masked_value: Optional[str] = None  # safe masked preview, never the full value


class WhatsAppStatusResponse(BaseModel):
    """Response model for GET /publish/status.

    configured=True only when all three required variables are non-empty.
    graph_base is the Graph API URL the service will use (hardcoded v20.0).
    """
    configured: bool
    graph_base: str
    access_token: WhatsAppStatusVar
    phone_number_id: WhatsAppStatusVar
    recipient_number: WhatsAppStatusVar
    maps_api_key_present: bool
