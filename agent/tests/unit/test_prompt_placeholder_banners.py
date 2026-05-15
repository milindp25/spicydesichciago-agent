"""Guards against accidentally shipping the hi/te placeholder prompts to
production without translation. The banner header MUST stay until a native
speaker has actually translated the body."""
from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "app" / "prompts"


def test_hindi_prompt_has_review_banner() -> None:
    body = (PROMPTS_DIR / "system.hi.md").read_text()
    assert body.lstrip().startswith("<!--")
    assert "REVIEW BEFORE PRODUCTION" in body.splitlines()[1]


def test_telugu_prompt_has_review_banner() -> None:
    body = (PROMPTS_DIR / "system.te.md").read_text()
    assert body.lstrip().startswith("<!--")
    assert "REVIEW BEFORE PRODUCTION" in body.splitlines()[1]


def test_english_prompt_has_no_banner() -> None:
    body = (PROMPTS_DIR / "system.en.md").read_text()
    assert "REVIEW BEFORE PRODUCTION" not in body
