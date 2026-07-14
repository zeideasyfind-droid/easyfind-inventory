from typing import Optional
from pydantic import BaseModel


class ExtractRequest(BaseModel):
    url: str


class Property(BaseModel):
    """Raw + normalized fields for one extracted listing. Field names
    mirror the Google Sheet column mapping (see google_sheets.py)."""

    property_id: str = ""
    extracted_at: Optional[str] = None
    portal_url: str = ""

    date: Optional[str] = None
    onboarding_status: Optional[str] = None
    property_location: Optional[str] = None
    society_name: Optional[str] = None
    owner_name: Optional[str] = None
    contact_number: Optional[str] = None
    bhk_label: Optional[str] = None
    bathrooms: Optional[int] = None
    balcony: Optional[int] = None
    area_label: Optional[str] = None
    floor_label: Optional[str] = None
    furnishing: Optional[str] = None
    tenant_preference: Optional[str] = None
    veg_non_veg: Optional[str] = None
    pets: Optional[str] = None
    rent: Optional[float] = None
    maintenance: Optional[float] = None
    deposit: Optional[float] = None
    available_from: Optional[str] = None
    negotiations: Optional[str] = None
    visit_timings: Optional[str] = None
    portal: str = "Housing.com"
    url: Optional[str] = None

    # Kept for duplicate matching (raw numeric bhk/area, not the display label)
    bhk: Optional[float] = None
    area: Optional[float] = None
