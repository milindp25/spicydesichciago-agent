"""Pipecat 1.1 voice-agent pipeline.

Pipecat is imported lazily so module-level import succeeds without the heavy
voice stack — the integration tests load `app.bot` to verify shape and the
real pipeline runs only when answering a call.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from app.config import AgentSettings
from app.intents import OwnerShortcut
from app.tools.api_client import ApiClient
from app.tools.definitions import TOOL_DEFINITIONS
from app.tools.handlers import handle_tool_call

log = logging.getLogger(__name__)

# Hard cap on caller<->bot conversation duration. After this, the bot tells the
# caller it's connecting them and triggers a transfer to the owner.
MAX_CALL_SECONDS = 90

# Don't blow up the LLM context with messages we'd never replay; persistence
# only needs enough turns to debug what was said.
TRANSCRIPT_TAIL = 40


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


def _build_call_context(
    *,
    history_note: str,
    from_phone: str,
    owner_available: bool,
    greeting: str,
) -> str:
    parts = [f"Call context — caller phone: {from_phone or 'unknown'}.", history_note]
    if not owner_available:
        parts.append(
            "Owner is currently OUTSIDE business hours — DO NOT call request_transfer. "
            "If the caller asks to speak to the owner, apologize and offer to take a "
            "message via take_message instead."
        )
    if greeting:
        parts.append(f'Use this exact opening line when greeting the caller: "{greeting}"')
    return " ".join(parts)


async def _persist_transcript(
    api: ApiClient, *, call_sid: str, messages: list[dict[str, Any]], started_at: float
) -> None:
    """Dump the tail of the conversation to the JSONL log on disconnect."""
    try:
        tail = messages[-TRANSCRIPT_TAIL:]
        cleaned = [
            {"role": m.get("role"), "content": str(m.get("content", ""))[:2000]}
            for m in tail
            if m.get("role") in {"user", "assistant", "system"}
        ]
        await api.append_event(
            call_sid=call_sid,
            kind="call_ended",
            payload={
                "duration_secs": round(time.time() - started_at, 1),
                "turns": len(cleaned),
                "transcript": cleaned,
            },
        )
    except Exception:
        log.exception("transcript persist failed")


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

    # Prefetch tenant snapshot + caller history. Both are best-effort —
    # failure here means the call still answers, just without the per-call
    # personalization.
    greeting = ""
    owner_available = True
    try:
        tenant_info = await api.get_tenant()
        greeting = tenant_info.get("greeting") or ""
        owner_available = bool(tenant_info.get("owner_available", True))
    except Exception:
        log.exception("tenant snapshot failed; defaulting owner_available=True")

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
            log.exception("tool error", extra={"name": params.function_name})
            payload: dict[str, Any] = {"error": str(exc)}
            with contextlib.suppress(Exception):
                await api.append_event(
                    call_sid=call_sid,
                    kind="tool_error",
                    payload={"tool": params.function_name, "error": str(exc)},
                )
        else:
            try:
                payload = json.loads(result_str)
            except Exception:
                payload = {"result": result_str}

        await params.result_callback(payload)

    llm.register_function(None, _tool_handler)

    tools = _tools_schema_from_definitions()
    context = LLMContext(
        messages=[
            {"role": "system", "content": load_system_prompt()},
            {
                "role": "system",
                "content": _build_call_context(
                    history_note=history_note,
                    from_phone=from_phone,
                    owner_available=owner_available,
                    greeting=greeting,
                ),
            },
        ],
        tools=tools,
    )
    aggregators = LLMContextAggregatorPair(context)

    # Owner-transfer shortcut is disabled after hours — falls back to the
    # LLM, which will offer to take a message instead of attempting transfer.
    pipeline_steps = [
        transport.input(),
        stt,
    ]
    if owner_available:
        pipeline_steps.append(OwnerShortcut(api=api, call_sid=call_sid))
    pipeline_steps += [
        aggregators.user(),
        llm,
        tts,
        transport.output(),
        aggregators.assistant(),
    ]

    pipeline = Pipeline(pipeline_steps)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=False,
            enable_usage_metrics=False,
        ),
    )

    started_at = time.time()
    timeout_task: asyncio.Task | None = None

    async def _force_transfer_after_timeout() -> None:
        try:
            await asyncio.sleep(MAX_CALL_SECONDS)
        except asyncio.CancelledError:
            return
        log.info(
            "call exceeded MAX_CALL_SECONDS — forcing transfer",
            extra={"call_sid": call_sid, "limit": MAX_CALL_SECONDS},
        )
        if owner_available:
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
        else:
            context.add_message(
                {
                    "role": "system",
                    "content": (
                        "The conversation has reached the 90-second cap. Wrap up: take a "
                        "message via take_message and tell the caller the owner will ring back."
                    ),
                }
            )
        try:
            await task.queue_frames([LLMRunFrame()])
        except Exception:
            log.exception("failed to queue transfer prompt at timeout")

    async def _on_started() -> None:
        try:
            await api.append_event(
                call_sid=call_sid,
                kind="call_started",
                payload={"from": from_phone, "owner_available": owner_available},
            )
        except Exception:
            log.exception("call_started log failed")

    @transport.event_handler("on_client_connected")
    async def _on_connected(_t: Any, _client: Any) -> None:
        nonlocal timeout_task
        await _on_started()
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
        await _persist_transcript(
            api,
            call_sid=call_sid,
            messages=list(context.messages),
            started_at=started_at,
        )
        await api.aclose()
