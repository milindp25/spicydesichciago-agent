from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.config import AgentSettings  # noqa: E402
from app.server import build_app  # noqa: E402

settings = AgentSettings()
app = build_app(settings)
