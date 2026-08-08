"""
Centralised configuration for DAWA P0-A.

Loading rules:
  - UPLIFTAI_API_KEY   : required at import time (needed for every Uplift call)
  - TEST_PHONE_NUMBER  : optional at load; validated at /api/test-call invocation
  - UPLIFT_ASSISTANT_ID: optional at load; validated at /api/test-call* invocation

The Singapore base URL is the ONLY Uplift base URL used in P0-A.
Pakistani outbound calling works ONLY through this region.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


UPLIFT_BASE_URL = "https://ap-southeast-1.api.upliftai.org/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Required at startup — every Uplift API call needs this
    upliftai_api_key: str

    # Optional at load; checked at call-time in the service layer
    test_phone_number: str | None = None
    uplift_assistant_id: str | None = None

    # Admin token for privileged endpoints (e.g. GET /api/call-log).
    # If unset those endpoints return 403. Set as DAWA_ADMIN_TOKEN in Replit Secrets.
    dawa_admin_token: str | None = None

    # Webhook secret for verifying Uplift session-complete callbacks.
    # Set as UPLIFT_WEBHOOK_SECRET in Replit Secrets.
    uplift_webhook_secret: str | None = None

    # Development mode — when True and UPLIFT_WEBHOOK_SECRET is absent, signature
    # verification is skipped with a warning (allows local dev without a secret).
    # Set DAWA_DEV_MODE=true ONLY in development; production must always have a secret.
    # Defaults to False (fail closed).
    dawa_dev_mode: bool = False


# Module-level singleton — import `settings` everywhere
settings = Settings()  # raises ValidationError with a clear message if UPLIFTAI_API_KEY is absent
