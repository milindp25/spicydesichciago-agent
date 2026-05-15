from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import firebase_admin  # noqa: E402
from firebase_admin import credentials as fb_credentials  # noqa: E402

from app.api.app_factory import build_app  # noqa: E402
from app.api.dependencies import AppState  # noqa: E402
from app.api.middleware.firebase_auth import FirebaseAuthVerifier  # noqa: E402
from app.infrastructure.cache import TtlCache  # noqa: E402
from app.infrastructure.config import AppSettings  # noqa: E402
from app.infrastructure.firestore_call_store import FirestoreCallStore  # noqa: E402
from app.infrastructure.firestore_caller_store import FirestoreCallerStore  # noqa: E402
from app.infrastructure.firestore_client import FirestoreClient  # noqa: E402
from app.infrastructure.firestore_message_store import FirestoreMessageStore  # noqa: E402
from app.infrastructure.firestore_owner_override_store import (  # noqa: E402
    FirestoreOwnerOverrideStore,
)
from app.infrastructure.firestore_transcript_store import (  # noqa: E402
    FirestoreTranscriptStore,
)
from app.infrastructure.logger import configure_logging, get_logger  # noqa: E402
from app.infrastructure.pickup_state import PickupStateStore  # noqa: E402
from app.infrastructure.square_client import (  # noqa: E402
    SquareCatalogAdapter,
    SquareLocationsAdapter,
    make_square_client,
)
from app.infrastructure.tenant_registry import load_tenants  # noqa: E402
from app.infrastructure.twilio_client import (  # noqa: E402
    NoopTwilioClient,
    RealTwilioClient,
    TwilioOps,
)
from app.services.catalog_service import CatalogService  # noqa: E402
from app.services.locations_service import LocationsService  # noqa: E402
from app.services.pickup_service import PickupService  # noqa: E402


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
        specials_category_id=settings.square_specials_category_id,
    )
    pickup_store = PickupStateStore("./data/pickup-state.json")
    pickup_service = PickupService(store=pickup_store, locations=locations_service)
    twilio: TwilioOps = (
        RealTwilioClient(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_from_number,
        )
        if settings.twilio_account_sid
        else NoopTwilioClient()
    )
    firestore_client = FirestoreClient(
        project_id=settings.firebase_project_id,
        service_account_path=settings.firebase_service_account_path,
    )
    db = firestore_client.db
    call_store = FirestoreCallStore(client=db)
    caller_store = FirestoreCallerStore(client=db)
    message_store = FirestoreMessageStore(client=db)
    owner_override_store = FirestoreOwnerOverrideStore(client=db)
    transcript_store = FirestoreTranscriptStore(client=db)

    # Initialize firebase_admin's default app (needed for auth.verify_id_token).
    # Idempotent: subsequent calls in tests are no-ops via the try/except.
    if not firebase_admin._apps:  # type: ignore[attr-defined]
        if settings.firebase_service_account_path:
            cred = fb_credentials.Certificate(settings.firebase_service_account_path)
            firebase_admin.initialize_app(cred, {"projectId": settings.firebase_project_id})
        else:
            firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id})

    admin_verifier = FirebaseAuthVerifier(allowed_emails=settings.admin_allowed_emails_list)
    state = AppState(
        tools_shared_secret=settings.tools_shared_secret,
        tenants=load_tenants(settings.configs_dir),
        locations_service=locations_service,
        catalog_service=catalog_service,
        pickup_service=pickup_service,
        square_webhook_signature_key=settings.square_webhook_signature_key,
        square_webhook_url=settings.square_webhook_url,
        twilio=twilio,
        agent_public_url=settings.agent_public_url,
        cors_origins=settings.cors_origin_list,
        call_store=call_store,
        caller_store=caller_store,
        message_store=message_store,
        owner_override_store=owner_override_store,
        transcript_store=transcript_store,
        admin_verifier=admin_verifier,
    )
    return build_app(state)


app = _build()
