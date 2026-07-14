from typing import List, Optional
from pydantic import BaseModel


class ExtractRequest(BaseModel):
    url: str


class Property(BaseModel):
    portal_url: str = ""
    property_id: str = ""
    title: Optional[str] = None
    rent: Optional[float] = None
    deposit: Optional[float] = None
    maintenance: Optional[float] = None
    bhk: Optional[float] = None
    bathrooms: Optional[int] = None
    balcony: Optional[int] = None
    furnishing: Optional[str] = None
    area: Optional[float] = None
    floor: Optional[str] = None
    property_type: Optional[str] = None
    parking: Optional[str] = None
    tenant_preference: Optional[str] = None
    pets: Optional[str] = None
    available_from: Optional[str] = None
    owner_name: Optional[str] = None
    contact_number: Optional[str] = None
    address: Optional[str] = None
    locality: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    amenities: List[str] = []
    description: Optional[str] = None
    extracted_at: Optional[str] = None
