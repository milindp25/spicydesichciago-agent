"""Hot-path intent shortcuts.

Some intents — most importantly "transfer me to a human" — are too important
to leave to the LLM, which can occasionally produce malformed tool calls and
leave the caller in silence. This module provides Pipecat frame processors
that match obvious caller intent on the raw STT transcription and trigger the
right action immediately, bypassing the LLM for those turns.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.tools.api_client import ApiClient

log = logging.getLogger(__name__)

# Conservative pattern — requires an explicit "transfer/connect/speak/talk"
# verb together with an owner/manager/human noun, so menu questions like
# "does the owner have a special?" don't trip it.
_OWNER_INTENT = re.compile(
    r"\b("
    r"(connect|transfer|put|get|patch)\s+(me\s+)?(through\s+)?(to|with)\s+(the\s+|your\s+|an\s+|a\s+)?(owner|manager|human|real\s+(person|human)|someone)"
    r"|(speak|talk)\s+(to|with)\s+(the\s+|your\s+|a\s+)?(owner|manager|human|real\s+(person|human)|someone(\s+else)?(\s+in\s+charge)?)"
    r"|i\s+(want|need|wanna|gotta)\s+(to\s+)?(speak|talk|connect)\s+(to|with)\s+(the\s+|your\s+|a\s+)?(owner|manager|human)"
    r"|transfer\s+me"
    r")\b",
    re.IGNORECASE,
)


def is_owner_transfer_request(text: str) -> bool:
    return bool(_OWNER_INTENT.search(text or ""))


class OwnerShortcut(FrameProcessor):
    """Intercepts transcriptions matching owner-transfer intent.

    On match: speaks a short stock line ("Hold on, connecting you now")
    and asynchronously calls the API's request_transfer endpoint after a
    short delay so the line has time to play before Twilio redirects
    the call. The original transcription is NOT forwarded, so the LLM
    never sees this turn — keeps the response instant and reliable.
    """

    SPEAK_LINE = "Hold on — connecting you to the owner now."
    # Delay between speaking the line and triggering the transfer, so the
    # caller hears the "connecting" line before Twilio terminates the stream.
    TRANSFER_DELAY_SECS = 2.0

    def __init__(self, *, api: ApiClient, call_sid: str) -> None:
        super().__init__()
        self._api = api
        self._call_sid = call_sid
        self._transfer_started = False
        # Holding a reference so the task isn't garbage-collected.
        self._transfer_task: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if (
            direction == FrameDirection.DOWNSTREAM
            and isinstance(frame, TranscriptionFrame)
            and not self._transfer_started
            and is_owner_transfer_request(frame.text or "")
        ):
            self._transfer_started = True
            log.info(
                "owner-transfer intent matched; bypassing LLM",
                extra={"call_sid": self._call_sid, "text": frame.text},
            )
            # Speak the stock line. Pushed downstream so it reaches the TTS
            # service that lives further down the pipeline.
            await self.push_frame(
                TTSSpeakFrame(self.SPEAK_LINE), FrameDirection.DOWNSTREAM
            )
            # Trigger the transfer asynchronously so we can return quickly
            # and let the TTS line play out.
            self._transfer_task = asyncio.create_task(self._do_transfer())
            # Swallow the original transcription so the LLM never sees it.
            return

        await self.push_frame(frame, direction)

    async def _do_transfer(self) -> None:
        try:
            await asyncio.sleep(self.TRANSFER_DELAY_SECS)
            result: dict[str, Any] = await self._api.request_transfer(
                call_sid=self._call_sid,
                reason="caller asked for owner (intent shortcut)",
            )
            log.info("transfer triggered via shortcut", extra={"result": result})
        except Exception:
            log.exception("intent shortcut transfer failed")
            self._transfer_started = False
