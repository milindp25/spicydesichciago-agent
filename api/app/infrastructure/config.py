from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    port: int = Field(8080, alias="PORT")
    log_level: str = Field("info", alias="LOG_LEVEL")
    app_env: Literal["development", "test", "production"] = Field("development", alias="APP_ENV")

    tools_shared_secret: str = Field(..., alias="TOOLS_SHARED_SECRET", min_length=32)

    square_access_token: str = Field(..., alias="SQUARE_ACCESS_TOKEN", min_length=1)
    square_environment: Literal["sandbox", "production"] = Field(..., alias="SQUARE_ENVIRONMENT")
    square_webhook_signature_key: str = Field(
        ..., alias="SQUARE_WEBHOOK_SIGNATURE_KEY", min_length=1
    )
    square_webhook_url: str = Field("", alias="SQUARE_WEBHOOK_URL")

    square_specials_category_id: str = Field("SPECIALS", alias="SQUARE_SPECIALS_CATEGORY_ID")

    configs_dir: str = Field(..., alias="CONFIGS_DIR", min_length=1)
    event_log_path: str = Field("./data/events.jsonl", alias="EVENT_LOG_PATH")

    twilio_account_sid: str = Field("", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field("", alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: str = Field("", alias="TWILIO_FROM_NUMBER")
    twilio_signing_secret: str = Field("", alias="TWILIO_SIGNING_SECRET")

    firebase_service_account_path: str = Field("", alias="FIREBASE_SERVICE_ACCOUNT_PATH")
    firebase_project_id: str = Field("spicy-desi-chicago", alias="FIREBASE_PROJECT_ID")

    agent_public_url: str = Field("", alias="AGENT_PUBLIC_URL")

    cors_origins: str = Field("", alias="CORS_ORIGINS")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
