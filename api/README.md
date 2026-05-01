# Spicy Desi API

FastAPI service exposing Square-backed endpoints for the Pipecat voice agent.

## Quick start

```
cd api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in keys
uvicorn app.main:app --reload --port 8080
```

## Tests

```
pytest
```

## Lint + typecheck

```
ruff check .
ruff format --check .
mypy app
```

## Architecture

```
app/
  api/                  Presentation layer (FastAPI routes)
    routes/             One file per resource
    dependencies.py     Auth, DI, app state
    app_factory.py      build_app(deps) -> FastAPI
  services/             Business logic
  domain/               Pydantic models — zero deps
  infrastructure/       Adapters: config, logger, cache, Square SDK,
                        tenant registry, JSONL event log
```

Layer rules: dependencies flow inward only. Routes only call services. Services only call infrastructure. Domain has no project deps.
