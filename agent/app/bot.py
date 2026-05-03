"""Pipecat 1.1 voice-agent pipeline.

Pipecat is imported lazily so module-level import succeeds without the heavy
voice stack — the integration tests load `app.bot` to verify shape and the
real pipeline runs only when answering a call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import AgentSettings
from app.tools.api_client import ApiClient
from app.tools.definitions import TOOL_DEFINITIONS
from app.tools.handlers import handle_tool_call


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


async def run_bot(
    websocket: Any,
    *,
    settings: AgentSettings,
    stream_sid: str,
    call_sid: str,
) -> None:
    """Build and run the Pipecat voice-agent pipeline for a single call."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
    )
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.services.cartesia.tts import CartesiaTTSService
    from pipecat.services.deepgram.stt import DeepgramSTTService
    from pipecat.services.groq.llm import GroqLLMService
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
            vad_analyzer=SileroVADAnalyzer(),
            serializer=serializer,
        ),
    )

    stt = DeepgramSTTService(api_key=settings.deepgram_api_key)
    llm = GroqLLMService(api_key=settings.groq_api_key, model="llama-3.3-70b-versatile")
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        voice_id=settings.cartesia_voice_id,
    )

    api = ApiClient(
        base_url=settings.tools_api_base,
        secret=settings.tools_shared_secret,
        tenant=settings.default_tenant,
    )

    async def _tool_handler(params: Any) -> None:
        """Pipecat passes a FunctionCallParams object; we dispatch to handle_tool_call."""
        result_str = await handle_tool_call(
            params.function_name,
            dict(params.arguments),
            api=api,
            call_sid=call_sid,
        )
        import json as _json

        try:
            payload = _json.loads(result_str)
        except Exception:
            payload = {"result": result_str}
        await params.result_callback(payload)

    # `None` registers the catch-all handler for every function call.
    llm.register_function(None, _tool_handler)

    tools = _tools_schema_from_definitions()
    context = LLMContext(
        messages=[{"role": "system", "content": load_system_prompt()}],
        tools=tools,
    )
    aggregators = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            aggregators.user(),
            llm,
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

    @transport.event_handler("on_client_connected")
    async def _on_connected(_t: Any, _client: Any) -> None:
        # Kick off the conversation — LLM produces the greeting on first run.
        context.add_message({"role": "user", "content": "Greet the caller now."})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_t: Any, _client: Any) -> None:
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    finally:
        await api.aclose()
