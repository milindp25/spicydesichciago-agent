"""SummaryGenerator — LLM-driven 1-sentence call summary.

Uses the same chat-completions client the main bot uses (Groq or any
OpenAI-compatible endpoint). The prompt strongly constrains the model
to a single sentence; we additionally cap output at 300 chars in case
the model ignores the constraint.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol


log = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 300


def build_summary_prompt(transcript_text: str) -> str:
    if not transcript_text.strip():
        return (
            "The conversation transcript is empty (call dropped before any "
            "speech). Return the single word: dropped."
        )
    return (
        "You are summarizing a phone call between a restaurant's AI assistant "
        "and a customer. Write ONE sentence (max 25 words) describing what "
        "the caller asked about and whether they got an answer. Use past "
        "tense. Do not use quotes or bullet points. Do not name the "
        "restaurant.\n\n"
        f"Transcript:\n{transcript_text}\n\n"
        "Summary (one sentence):"
    )


class _ChatClient(Protocol):
    chat: Any  # has .completions.create(...)


class SummaryGenerator:
    def __init__(self, *, llm_client: _ChatClient, model: str) -> None:
        self._client = llm_client
        self._model = model

    async def generate(self, transcript_text: str) -> str:
        prompt = build_summary_prompt(transcript_text)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "You are a concise summarizer."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=80,
                temperature=0.2,
            )
            content = (response.choices[0].message.content or "").strip()
        except Exception:
            log.exception("summary generation failed")
            return ""

        if len(content) > MAX_SUMMARY_CHARS:
            content = content[: MAX_SUMMARY_CHARS - 3] + "..."
        return content
