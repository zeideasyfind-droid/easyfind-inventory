"""Central configuration for the EasyFind Inventory Engine.

All configuration comes from environment variables. Nothing here is
hardcoded — secrets must be provided via the environment.
"""
import os


class Settings:
    """Lazily reads environment variables so tests / imports never fail
    even if some values are missing (routes validate what they need)."""

    @property
    def FIRECRAWL_API_KEY(self) -> str:
        return os.environ.get("FIRECRAWL_API_KEY", "")

    @property
    def GOOGLE_SHEET_ID(self) -> str:
        return os.environ.get("GOOGLE_SHEET_ID", "")

    @property
    def GOOGLE_SERVICE_ACCOUNT_JSON(self) -> str:
        # Accept both names — GOOGLE_SERVICE_ACCOUNT is the Replit secret name
        return os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or os.environ.get("GOOGLE_SERVICE_ACCOUNT", "")

    @property
    def GOOGLE_DRIVE_FOLDER_ID(self) -> str:
        return os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

    @property
    def PORT(self) -> int:
        return int(os.environ.get("PORT", "8080"))

    # --- Module 2: Property Publishing Engine ---

    @property
    def GOOGLE_MAPS_API_KEY(self) -> str:
        return os.environ.get("GOOGLE_MAPS_API_KEY", "")

    # --- Module 3: Meta Commerce Catalog + Cloudinary ---

    @property
    def META_CATALOG_ID(self) -> str:
        # Explicit production catalog ID; can be overridden via env var.
        return os.environ.get("META_CATALOG_ID", "1033806272839748")

    @property
    def CLOUDINARY_CLOUD_NAME(self) -> str:
        return os.environ.get("CLOUDINARY_CLOUD_NAME", "")

    @property
    def CLOUDINARY_API_KEY(self) -> str:
        return os.environ.get("CLOUDINARY_API_KEY", "")

    @property
    def CLOUDINARY_API_SECRET(self) -> str:
        return os.environ.get("CLOUDINARY_API_SECRET", "")

    @property
    def WHATSAPP_ACCESS_TOKEN(self) -> str:
        # Accept both names — WHATSAPP_TOKEN is the Replit secret name
        return os.environ.get("WHATSAPP_ACCESS_TOKEN") or os.environ.get("WHATSAPP_TOKEN", "")

    @property
    def WHATSAPP_PHONE_NUMBER_ID(self) -> str:
        # Accept both names — PHONE_NUMBER_ID is the Replit secret name
        return os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or os.environ.get("PHONE_NUMBER_ID", "")

    @property
    def WHATSAPP_RECIPIENT_NUMBER(self) -> str:
        return os.environ.get("WHATSAPP_RECIPIENT_NUMBER", "")


settings = Settings()
