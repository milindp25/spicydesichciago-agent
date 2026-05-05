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
from collections.abc import Awaitable, Callable
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


def _coerce_tool_args(raw_args: Any) -> dict[str, Any]:
    """LLM SDKs disagree on how to pass tool args — normalize to a dict."""
    if raw_args is None:
        return {}
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args) if raw_args else {}
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return dict(raw_args)


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


async def _prefetch_call_state(
    api: ApiClient, *, from_phone: str
) -> tuple[str, bool, str]:
    """Returns (greeting, owner_available, history_note). Best-effort."""
    greeting = ""
    owner_available = True
    try:
        info = await api.get_tenant()
        greeting = info.get("greeting") or ""
        owner_available = bool(info.get("owner_available", True))
    except Exception:
        log.exception("tenant snapshot failed; defaulting owner_available=True")

    history_note = "First-time caller."
    if from_phone:
        try:
            history = await api.get_caller_history(phone=from_phone)
            history_note = _format_caller_history(history)
        except Exception:
            log.exception("caller history lookup failed", extra={"phone": from_phone})

    return greeting, owner_available, history_note


def _build_llm(settings: AgentSettings) -> Any:
    from pipecat.services.groq.llm import GroqLLMService
    from pipecat.services.openai.llm import OpenAILLMService

    if settings.llm_base_url:
        log.info(
            "using OpenAI-compatible LLM",
            extra={"base_url": settings.llm_base_url, "model": settings.llm_model},
        )
        return OpenAILLMService(
            api_key=settings.llm_api_key or "not-needed",
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
    return GroqLLMService(
        api_key=settings.groq_api_key,
        model=settings.llm_model or "llama-3.3-70b-versatile",
    )


def _build_transport(
    websocket: Any, *, stream_sid: str, call_sid: str
) -> Any:
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )
    return FastAPIWebsocketTransport(
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


def _build_stt(settings: AgentSettings) -> Any:
    from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings

    return DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTSettings(model="nova-3", language="en-US"),
    )


def _build_tts(settings: AgentSettings) -> Any:
    from pipecat.services.cartesia.tts import CartesiaTTSService, CartesiaTTSSettings

    return CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        settings=CartesiaTTSSettings(
            voice=settings.cartesia_voice_id,
            model="sonic-2",
        ),
    )


def _make_tool_handler(
    *, api: ApiClient, call_sid: str, from_phone: str
) -> Callable[[Any], Awaitable[None]]:
    async def _handler(params: Any) -> None:
        args = _coerce_tool_args(params.arguments)
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

    return _handler


def _build_pipeline(
    *,
    transport: Any,
    stt: Any,
    llm: Any,
    tts: Any,
    aggregators: Any,
    owner_shortcut: OwnerShortcut | None,
) -> Any:
    from pipecat.pipeline.pipeline import Pipeline

    steps = [transport.input(), stt]
    if owner_shortcut is not None:
        steps.append(owner_shortcut)
    steps += [
        aggregators.user(),
        llm,
        tts,
        transport.output(),
        aggregators.assistant(),
    ]
    return Pipeline(steps)


async def run_bot(
    websocket: Any,
    *,
    settings: AgentSettings,
    stream_sid: str,
    call_sid: str,
    from_phone: str = "",
) -> None:
    """Build and run the Pipecat voice-agent pipeline for a single call."""
    from pipecat.frames.frames import LLMRunFrame
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
    )

    api = ApiClient(
        base_url=settings.tools_api_base,
        secret=settings.tools_shared_secret,
        tenant=settings.default_tenant,
    )

    greeting, owner_available, history_note = await _prefetch_call_state(
        api, from_phone=from_phone
    )

    transport = _build_transport(websocket, stream_sid=stream_sid, call_sid=call_sid)
    stt = _build_stt(settings)
    llm = _build_llm(settings)
    tts = _build_tts(settings)

    llm.register_function(
        None, _make_tool_handler(api=api, call_sid=call_sid, from_phone=from_phone)
    )

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
        tools=_tools_schema_from_definitions(),
    )
    aggregators = LLMContextAggregatorPair(context)

    # Owner-transfer shortcut is disabled after hours — the LLM falls back
    # to take_message instead of attempting transfer.
    owner_shortcut = (
        OwnerShortcut(api=api, call_sid=call_sid) if owner_available else None
    )

    pipeline = _build_pipeline(
        transport=transport,
        stt=stt,
        llm=llm,
        tts=tts,
        aggregators=aggregators,
        owner_shortcut=owner_shortcut,
    )

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
            cap_msg = (
                "The conversation has reached the 90-second cap. Politely tell the "
                "caller you're connecting them to the owner now, and immediately call "
                "request_transfer with reason='90-second cap reached'."
            )
        else:
            cap_msg = (
                "The conversation has reached the 90-second cap. Wrap up: take a "
                "message via take_message and tell the caller the owner will ring back."
            )
        context.add_message({"role": "system", "content": cap_msg})
        try:
            await task.queue_frames([LLMRunFrame()])
        except Exception:
            log.exception("failed to queue transfer prompt at timeout")

    @transport.event_handler("on_client_connected")
    async def _on_connected(_t: Any, _client: Any) -> None:
        nonlocal timeout_task
        with contextlib.suppress(Exception):
            await api.append_event(
                call_sid=call_sid,
                kind="call_started",
                payload={"from": from_phone, "owner_available": owner_available},
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
        await _persist_transcript(
            api,
            call_sid=call_sid,
            messages=list(context.messages),
            started_at=started_at,
        )
        await api.aclose()
