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
