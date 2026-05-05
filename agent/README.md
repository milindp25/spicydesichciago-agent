# Spicy Desi Voice Agent

Pipecat-based voice agent that answers calls for the Spicy Desi food truck.
Twilio terminates the call, streams audio over a Media Stream WebSocket, and the
Pipecat pipeline runs:

```
Silero VAD → Deepgram Nova-3 STT → Groq Llama 3.3 70B (tool calls) → Cartesia Sonic-2 TTS
```

Tool calls (menu lookup, today's pickup, take-message, transfer-to-owner) hit
the Plan 1 API at `TOOLS_API_BASE` with `X-Tools-Auth: $TOOLS_SHARED_SECRET`.

## Setup

```bash
cd agent
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # then fill in keys
```

## Run

```bash
uvicorn app.main:app --port 8090
```

## Local end-to-end testing

You'll have THREE processes running:

1. **API** — Plan 1 service, port 8080
   ```bash
   cd api && source .venv/bin/activate
   uvicorn app.main:app --port 8080
   ```

2. **Agent** — this service, port 8090
   ```bash
   cd agent && source .venv/bin/activate
   uvicorn app.main:app --port 8090
   ```

3. **ngrok** — public tunnel so Twilio can reach the agent
   ```bash
   ngrok http 8090
   ```
   Note the URL it gives you, e.g. `https://abc123.ngrok-free.app`.

4. **Twilio number config** — in Twilio Console → Phone Numbers → your number:
   - Voice & Fax → "A call comes in" → Webhook → `https://abc123.ngrok-free.app/twilio/inbound` (HTTP POST)
   - Save.

5. **API .env update** — set `AGENT_PUBLIC_URL=https://abc123.ngrok-free.app` and restart the API so transfers can build the right TwiML URLs.

6. **Call your Twilio number** from any phone. You should hear the agent greeting.

## Tests

```bash
pytest -q
ruff check .
ruff format --check .
```
