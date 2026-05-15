"""Pipecat 1.1 voice-agent pipeline.

Pipecat is imported lazily so module-level import succeeds without the heavy
voice stack — the integration tests load `app.bot` to verify shape and the
real pipeline runs only when answering a call.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AgentSettings
from app.intents import OwnerShortcut
from app.outcome_tracker import OutcomeTracker
from app.summary import SummaryGenerator
from app.tools.api_client import ApiClient
from app.tools.definitions import TOOL_DEFINITIONS
from app.tools.handlers import handle_tool_call
from app.transcript_buffer import TranscriptBuffer

log = logging.getLogger(__name__)

# Hard cap on caller<->bot conversation duration. After this, the bot tells the
# caller it's connecting them and triggers a transfer to the owner.
MAX_CALL_SECONDS = 90


def load_system_prompt() -> str:
    return (Path(__file__).parent / "prompts" / "system.md").read_text()


def _tools_schema_from_definitions() -> Any:
    """Convert the OpenAI-style TOOL_DEFINITIONS into a Pipecat ToolsSchema."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema

    fns = []
    for tool in TOOL_DEFINITIONS:
        f = tool["function"]
        params = f.get("parameters", {})
        fns.append(
            FunctionSchema(
                name=f["name"],
                description=f["description"],
                properties=params.get("properties", {}),
                required=params.get("required", []),
            )
        )
    return ToolsSchema(standard_tools=fns)


def _format_caller_history(history: dict[str, Any]) -> str:
    """Render caller-history JSON as a short note for the LLM context."""
    if not history.get("is_returning"):
        return "First-time caller."
    events = history.get("events") or []
    lines = [
        f"Returning caller — {history.get('call_count', 0)} prior call(s). Recent activity:"
    ]
    for ev in events[:3]:
        summary = (ev.get("summary") or ev.get("kind") or "").strip()
        if summary:
            lines.append(f"- {summary}")
    return "\n".join(lines)


async def run_bot(
    websocket: Any,
    *,
    settings: AgentSettings,
    stream_sid: str,
    call_sid: str,
    from_phone: str = "",
) -> None:
    """Build and run the Pipecat voice-agent pipeline for a single call."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.frames.frames import LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
    )
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.services.cartesia.tts import CartesiaTTSService, CartesiaTTSSettings
    from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings
    from pipecat.services.groq.llm import GroqLLMService
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )
    from pipecat.frames.frames import Frame, LLMTextFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    class _TranscriptTap(FrameProcessor):
        """Snoop TranscriptionFrame (user) and LLMTextFrame (assistant) into
        TranscriptBuffer without modifying the frame stream."""

        def __init__(self, buf: TranscriptBuffer) -> None:
            super().__init__()
            self._buf = buf

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame):
                self._buf.add_user(getattr(frame, "text", None))
            elif isinstance(frame, LLMTextFrame):
                self._buf.add_assistant(getattr(frame, "text", None))
            await self.push_frame(frame, direction)

    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(stop_secs=0.4, start_secs=0.2)
            ),
            serializer=serializer,
        ),
    )

    stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTSettings(model="nova-3", language="en-US"),
    )
    if settings.llm_base_url:
        # OpenAI-compatible endpoint — Ollama, LM Studio, vLLM, OpenRouter, etc.
        log.info(
            "using OpenAI-compatible LLM",
            extra={"base_url": settings.llm_base_url, "model": settings.llm_model},
        )
        llm = OpenAILLMService(
            api_key=settings.llm_api_key or "not-needed",
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
    else:
        llm = GroqLLMService(
            api_key=settings.groq_api_key,
            model=settings.llm_model or "llama-3.3-70b-versatile",
        )
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        settings=CartesiaTTSSettings(
            voice=settings.cartesia_voice_id,
            model="sonic-2",
        ),
    )

    api = ApiClient(
        base_url=settings.tools_api_base,
        secret=settings.tools_shared_secret,
        tenant=settings.default_tenant,
    )

    transcript_buffer = TranscriptBuffer()
    outcome_tracker = OutcomeTracker()

    from pathlib import Path

    from app.event_buffer import EventBuffer

    event_buffer = EventBuffer(
        post_fn=lambda call_sid, kind, payload: api.append_event(
            call_sid=call_sid, kind=kind, payload=payload
        ),
        fallback_path=Path("/tmp/spicy-desi-failed-events.jsonl"),
    )
    await event_buffer.start()

    # SummaryGenerator uses a parallel chat-completions client (Groq or
    # OpenAI-compatible). Pipecat's LLM service wraps these but doesn't
    # expose them publicly, so we build a parallel client with the same
    # config. Imports are lazy to preserve the module-level-light pattern.
    if settings.llm_base_url:
        from openai import AsyncOpenAI

        summary_client: Any = AsyncOpenAI(
            api_key=settings.llm_api_key or "not-needed",
            base_url=settings.llm_base_url,
        )
    else:
        from groq import AsyncGroq

        summary_client = AsyncGroq(api_key=settings.groq_api_key)

    summary_gen = SummaryGenerator(
        llm_client=summary_client,
        model=settings.llm_model or "llama-3.3-70b-versatile",
    )

    # Best-effort caller history lookup. Failure is non-fatal (e.g. API down,
    # unknown caller, no events file) — we just treat them as a new caller.
    history_note = "First-time caller."
    if from_phone:
        try:
            history = await api.get_caller_history(phone=from_phone)
            history_note = _format_caller_history(history)
        except Exception:
            log.exception("caller history lookup failed", extra={"phone": from_phone})

    async def _tool_handler(params: Any) -> None:
        raw_args = params.arguments
        if raw_args is None:
            args: dict[str, Any] = {}
        elif isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args) if raw_args else {}
            except Exception:
                parsed = {}
            args = parsed if isinstance(parsed, dict) else {}
        else:
            args = dict(raw_args)

        try:
            result_str = await handle_tool_call(
                params.function_name,
                args,
                api=api,
                call_sid=call_sid,
                from_phone=from_phone,
            )
        except Exception as exc:
            payload: dict[str, Any] = {"error": str(exc)}
        else:
            try:
                payload = json.loads(result_str)
            except Exception:
                payload = {"result": result_str}

        outcome_tracker.record_tool(
            params.function_name, success="error" not in payload
        )

        await params.result_callback(payload)

    llm.register_function(None, _tool_handler)

    tools = _tools_schema_from_definitions()
    context = LLMContext(
        messages=[
            {"role": "system", "content": load_system_prompt()},
            {
                "role": "system",
                "content": (
                    f"Call context — caller phone: {from_phone or 'unknown'}. "
                    f"{history_note}"
                ),
            },
        ],
        tools=tools,
    )
    aggregators = LLMContextAggregatorPair(context)

    owner_shortcut = OwnerShortcut(api=api, call_sid=call_sid)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            _TranscriptTap(transcript_buffer),
            owner_shortcut,  # short-circuits "connect me to the owner" before LLM
            aggregators.user(),
            llm,
            _TranscriptTap(transcript_buffer),
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=False,
            enable_usage_metrics=False,
        ),
    )

    timeout_task: asyncio.Task | None = None
    started_at: datetime | None = None

    async def _force_transfer_after_timeout() -> None:
        try:
            await asyncio.sleep(MAX_CALL_SECONDS)
        except asyncio.CancelledError:
            return
        log.info(
            "call exceeded MAX_CALL_SECONDS — forcing transfer",
            extra={"call_sid": call_sid, "limit": MAX_CALL_SECONDS},
        )
        # Tell the LLM to wrap up + transfer. The LLM's next reply should
        # call request_transfer.
        context.add_message(
            {
                "role": "system",
                "content": (
                    "The conversation has reached the 90-second cap. Politely tell the "
                    "caller you're connecting them to the owner now, and immediately call "
                    "request_transfer with reason='90-second cap reached'."
                ),
            }
        )
        try:
            await task.queue_frames([LLMRunFrame()])
        except Exception:
            log.exception("failed to queue transfer prompt at timeout")

    @transport.event_handler("on_client_connected")
    async def _on_connected(_t: Any, _client: Any) -> None:
        nonlocal timeout_task, started_at
        started_at = datetime.now(timezone.utc)
        # Best-effort lifecycle: record call start (errors logged + swallowed)
        await api.record_call_start(
            call_sid=call_sid,
            started_at=started_at,
            caller_phone=from_phone or "+0",
            from_number="",
        )
        context.add_message({"role": "user", "content": "Greet the caller now."})
        await task.queue_frames([LLMRunFrame()])
        timeout_task = asyncio.create_task(_force_transfer_after_timeout())

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_t: Any, _client: Any) -> None:
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    finally:
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()

        # Lifecycle close: record end + summary (best-effort, never raise)
        if started_at is not None:
            ended_at = datetime.now(timezone.utc)
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)
            # Outcome derived from the last significant tool call (see
            # OutcomeTracker). Defaults to "resolved" when no significant
            # tool fired.
            await api.record_call_end(
                call_sid=call_sid,
                ended_at=ended_at,
                outcome=outcome_tracker.final_outcome(),
                duration_ms=duration_ms,
                caller_phone=from_phone or "+0",
                from_number="",
            )

            # Generate summary (best-effort — empty transcript returns ""
            # via SummaryGenerator; we then skip the summary write).
            if len(transcript_buffer) > 0:
                summary_text = await summary_gen.generate(transcript_buffer.as_text())
                if summary_text:
                    await api.record_call_summary(call_sid=call_sid, summary=summary_text)

        await event_buffer.stop()
        await api.aclose()
