"""Pipecat pipeline factory.

Pipecat itself is imported lazily so that the rest of the agent (config,
api_client, tool handlers, FastAPI routing, tests) can run without the heavy
voice-stack install. The smoke import test in `tests/unit/test_bot_module.py`
exercises just the module-level shape; the real pipeline is exercised end-to-end
during local Twilio call testing (Task 12).
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


async def run_bot(websocket: Any, *, settings: AgentSettings, call_sid: str) -> None:
    """Build and run the Pipecat voice-agent pipeline for a single call."""
    # Lazy imports — pipecat-ai is only required when actually answering a call.
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineTask
    from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
    from pipecat.services.cartesia import CartesiaTTSService
    from pipecat.services.deepgram import DeepgramSTTService
    from pipecat.services.groq import GroqLLMService
    from pipecat.transports.network.fastapi_websocket import FastAPIWebsocketTransport
    from pipecat.vad.silero import SileroVADAnalyzer

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketTransport.Params(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            add_wav_header=False,
            serializer=None,  # Twilio integration configures this; see Pipecat docs.
        ),
    )

    stt = DeepgramSTTService(api_key=settings.deepgram_api_key, language="multi")
    llm = GroqLLMService(api_key=settings.groq_api_key, model="llama-3.3-70b-versatile")
    tts = CartesiaTTSService(api_key=settings.cartesia_api_key, voice_id=settings.cartesia_voice_id)

    api = ApiClient(
        base_url=settings.tools_api_base,
        secret=settings.tools_shared_secret,
        tenant=settings.default_tenant,
    )

    async def _tool_handler(name: str, args: dict[str, Any]) -> str:
        return await handle_tool_call(name, args, api=api, call_sid=call_sid)

    # Pipecat's exact tool-registration API varies by version. The shape here
    # reflects the 0.0.50 pattern at design time — verify against your installed
    # pipecat-ai release and adapt if needed.
    llm.register_function(None, _tool_handler)
    for tool in TOOL_DEFINITIONS:
        llm.register_tool(tool)

    OpenAILLMContext(
        messages=[{"role": "system", "content": load_system_prompt()}],
        tools=TOOL_DEFINITIONS,
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            llm,
            tts,
            transport.output(),
        ]
    )

    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    try:
        await runner.run(task)
    finally:
        await api.aclose()
