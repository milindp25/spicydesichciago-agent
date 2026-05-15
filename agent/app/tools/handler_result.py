"""Error wrapper for tool handlers — turns Python exceptions into a
JSON payload the LLM speaks instead of going silent.

The contract with the system prompt: when a tool returns a payload
with both `error` and `voice_fallback` keys, the model should say
the voice_fallback string verbatim (or a close paraphrase) and offer
to take a message. The prompt's rule for this is in system.md.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import httpx

log = logging.getLogger(__name__)


DEFAULT_VOICE_FALLBACK = (
    "Hmm, looks like I can't pull that up right now. "
    "Want me to take a message and we'll call you back?"
)


def error_payload(error: str, *, voice_fallback: str | None = None) -> str:
    """Serialize an error+fallback into the JSON shape tool handlers
    return on failure."""
    return json.dumps(
        {
            "error": error,
            "voice_fallback": voice_fallback or DEFAULT_VOICE_FALLBACK,
        }
    )


async def safe_call(
    fn: Callable[[], Awaitable[Any]],
    *,
    voice_fallback: str | None = None,
) -> str:
    """Run fn() and JSON-serialize its return value. On any exception,
    log it and return error_payload(...) instead. Always returns a string
    safe to pass back to the LLM as a tool result."""
    try:
        result = await fn()
        return json.dumps(result)
    except httpx.TimeoutException as e:
        log.warning("tool call timeout", extra={"detail": str(e)})
        return error_payload(f"API timeout: {e}", voice_fallback=voice_fallback)
    except httpx.HTTPError as e:
        log.warning("tool call HTTP error", extra={"detail": str(e)})
        return error_payload(f"API error: {e}", voice_fallback=voice_fallback)
    except Exception as e:
        log.exception("tool call unexpected error")
        return error_payload(f"unexpected: {type(e).__name__}", voice_fallback=voice_fallback)
