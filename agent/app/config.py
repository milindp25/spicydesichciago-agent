from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # Multilingual DTMF IVR. Defaults to English only — the inbound route
    # short-circuits to a single-language Stream when len(languages_enabled)==1,
    # so production stays unchanged unless this env explicitly opts in to more.
    # Accepts a comma-separated string from env, e.g. AGENT_LANGUAGES_ENABLED=en,hi,te.
    # NoDecode tells pydantic-settings NOT to JSON-decode the raw env string —
    # we want a plain CSV string handed to the validator below.
    languages_enabled: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["en"], alias="AGENT_LANGUAGES_ENABLED"
    )
    # Per-language Cartesia voice IDs. Empty -> fall back to cartesia_voice_id.
    cartesia_voice_id_hi: str = Field("", alias="CARTESIA_VOICE_ID_HI")
    cartesia_voice_id_te: str = Field("", alias="CARTESIA_VOICE_ID_TE")
    # Per-language Deepgram STT language codes (nova-3 supports many).
    deepgram_language_en: str = Field("en-US", alias="DEEPGRAM_LANGUAGE_EN")
    deepgram_language_hi: str = Field("hi", alias="DEEPGRAM_LANGUAGE_HI")
    deepgram_language_te: str = Field("te", alias="DEEPGRAM_LANGUAGE_TE")

    @field_validator("languages_enabled", mode="before")
    @classmethod
    def _split_languages_csv(cls, v: object) -> object:
        """Parse AGENT_LANGUAGES_ENABLED as CSV when provided as a string."""
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return parts or ["en"]
        return v
