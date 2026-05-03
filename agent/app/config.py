from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore")

    port: int = Field(8090, alias="PORT")
    log_level: str = Field("info", alias="LOG_LEVEL")

    tools_api_base: str = Field(..., alias="TOOLS_API_BASE")
    tools_shared_secret: str = Field(..., alias="TOOLS_SHARED_SECRET", min_length=32)
    default_tenant: str = Field("spicy-desi", alias="DEFAULT_TENANT")

    groq_api_key: str = Field(..., alias="GROQ_API_KEY", min_length=1)
    deepgram_api_key: str = Field(..., alias="DEEPGRAM_API_KEY", min_length=1)
    cartesia_api_key: str = Field(..., alias="CARTESIA_API_KEY", min_length=1)
    cartesia_voice_id: str = Field(..., alias="CARTESIA_VOICE_ID", min_length=1)

    twilio_auth_token: str = Field("", alias="TWILIO_AUTH_TOKEN")
