from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import AppState
from app.api.routes import (
    address,
    callers,
    calls,
    events,
    health,
    hours,
    locations,
    menu,
    messages,
    pickup,
    sms,
    specials,
    transfers,
    webhooks_square,
)


def build_app(deps: AppState) -> FastAPI:
    app = FastAPI(title="Spicy Desi API")
    app.state.deps = deps

    if deps.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=deps.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["X-Tools-Auth", "Content-Type"],
            allow_credentials=False,
        )

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(_: object, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "invalid request", "details": exc.errors()}, status_code=400)

    app.include_router(health.router)
    app.include_router(locations.router)
    app.include_router(hours.router)
    app.include_router(address.router)
    app.include_router(menu.router)
    app.include_router(specials.router)
    app.include_router(messages.router)
    app.include_router(transfers.router)
    app.include_router(events.router)
    app.include_router(pickup.router)
    app.include_router(sms.router)
    app.include_router(callers.router)
    app.include_router(calls.router)
    app.include_router(webhooks_square.router)
    return app
