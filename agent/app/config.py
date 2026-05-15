from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore")

    port: int = Field(8090, alias="PORT")
    log_level: str = Field("info", alias="LOG_LEVEL")
    app_env: Literal["development", "test", "production"] = Field("development", alias="APP_ENV")

    tools_api_base: str = Field(..., alias="TOOLS_API_BASE")
    tools_shared_secret: str = Field(..., alias="TOOLS_SHARED_SECRET", min_length=32)
    default_tenant: str = Field("spicy-desi", alias="DEFAULT_TENANT")

    groq_api_key: str = Field(..., alias="GROQ_API_KEY", min_length=1)

    # Optional override: point at any OpenAI-compatible LLM endpoint
    # (Ollama, LM Studio, vLLM, OpenRouter, etc.). When set, takes precedence
    # over Groq. Useful for local testing without hitting Groq rate limits.
    llm_base_url: str = Field("", alias="LLM_BASE_URL")
    llm_model: str = Field("llama-3.3-70b-versatile", alias="LLM_MODEL")
    llm_api_key: str = Field("", alias="LLM_API_KEY")
    deepgram_api_key: str = Field(..., alias="DEEPGRAM_API_KEY", min_length=1)
    cartesia_api_key: str = Field(..., alias="CARTESIA_API_KEY", min_length=1)
    cartesia_voice_id: str = Field(..., alias="CARTESIA_VOICE_ID", min_length=1)

    twilio_auth_token: str = Field("", alias="TWILIO_AUTH_TOKEN")

    # VAD timings (seconds). stop_secs is how long to wait after the caller
    # stops speaking before considering their turn done; start_secs is the
    # minimum speech duration to trigger a start-of-speech event. Tuneable
    # via env without redeploys — useful for A/B testing barge-in feel.
    vad_stop_secs: float = Field(0.6, alias="AGENT_VAD_STOP_SECS")
    vad_start_secs: float = Field(0.2, alias="AGENT_VAD_START_SECS")
