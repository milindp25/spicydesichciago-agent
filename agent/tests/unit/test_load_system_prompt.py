from __future__ import annotations

from app.bot import load_system_prompt


def test_load_system_prompt_default_is_english() -> None:
    body = load_system_prompt()
    # English body markers — the system.en.md opening line.
    assert "Spicy Desi" in body
    assert "REVIEW BEFORE PRODUCTION" not in body


def test_load_system_prompt_explicit_en() -> None:
    body = load_system_prompt("en")
    assert "Spicy Desi" in body
    assert "REVIEW BEFORE PRODUCTION" not in body


def test_load_system_prompt_hi_has_banner() -> None:
    body = load_system_prompt("hi")
    assert "REVIEW BEFORE PRODUCTION" in body
    # Body still contains the English placeholder content for now.
    assert "Spicy Desi" in body


def test_load_system_prompt_te_has_banner() -> None:
    body = load_system_prompt("te")
    assert "REVIEW BEFORE PRODUCTION" in body
    assert "Spicy Desi" in body


def test_load_system_prompt_unknown_language_falls_back_to_en() -> None:
    body = load_system_prompt("xx")
    assert "Spicy Desi" in body
    assert "REVIEW BEFORE PRODUCTION" not in body
