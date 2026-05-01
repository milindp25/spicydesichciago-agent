from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.api.app_factory import build_app  # noqa: E402
from app.api.dependencies import AppState  # noqa: E402
from app.infrastructure.cache import TtlCache  # noqa: E402
from app.infrastructure.config import AppSettings  # noqa: E402
from app.infrastructure.event_log import JsonlEventLog  # noqa: E402
from app.infrastructure.logger import configure_logging, get_logger  # noqa: E402
from app.infrastructure.square_client import (  # noqa: E402
    SquareCatalogAdapter,
    SquareLocationsAdapter,
    make_square_client,
)
from app.infrastructure.tenant_registry import load_tenants  # noqa: E402
from app.services.catalog_service import CatalogService  # noqa: E402
from app.services.locations_service import LocationsService  # noqa: E402


def _build() -> FastAPI:
    settings = AppSettings()
    configure_logging(settings.log_level)
    log = get_logger("startup")
    log.info("loading tenants", configs_dir=settings.configs_dir)

    sq_client = make_square_client(
        access_token=settings.square_access_token,
        environment=settings.square_environment,
    )
    locations_service = LocationsService(
        api=SquareLocationsAdapter(sq_client),
        cache=TtlCache(ttl_seconds=60 * 60),
    )
    catalog_service = CatalogService(
        api=SquareCatalogAdapter(sq_client),
        cache=TtlCache(ttl_seconds=5 * 60),
        specials_category_id="SPECIALS",
    )
    state = AppState(
        tools_shared_secret=settings.tools_shared_secret,
        tenants=load_tenants(settings.configs_dir),
        locations_service=locations_service,
        catalog_service=catalog_service,
        event_log=JsonlEventLog(settings.event_log_path),
        square_webhook_signature_key=settings.square_webhook_signature_key,
        square_webhook_url=settings.square_webhook_url,
    )
    return build_app(state)


app = _build()
