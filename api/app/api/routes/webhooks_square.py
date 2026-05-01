from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.api.dependencies import get_state

router = APIRouter(prefix="/api/webhooks")


@router.post("/square")
async def square_webhook(
    request: Request,
    x_square_hmacsha256_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    state = get_state(request)
    body = await request.body()
    expected = base64.b64encode(
        hmac.new(
            state.square_webhook_signature_key.encode(),
            (state.square_webhook_url + body.decode()).encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    provided = x_square_hmacsha256_signature or ""
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "invalid signature")
    state.catalog_service.invalidate()
    state.locations_service.cache().clear()
    return {"ok": True}
