from __future__ import annotations

import json
from typing import Any

from app.tools.api_client import ApiClient
from app.tools.handler_result import error_payload, safe_call


# Tool-specific voice fallbacks. The default ("can't pull that up,
# want me to take a message?") is fine for most tools, but a few need
# tighter phrasing — especially take_message itself, which would loop
# if it offered to take a message on failure.
_FALLBACKS: dict[str, str] = {
    "search_menu": (
        "I'm having trouble pulling up the menu just now. "
        "Want me to take a message and we'll call you back with details?"
    ),
    "list_menu_categories": (
        "I'm having trouble pulling up the menu just now. "
        "Want me to take a message and we'll call you back with details?"
    ),
    "list_full_menu": (
        "I'm having trouble pulling up the menu just now. "
        "Want me to take a message and we'll call you back with details?"
    ),
    "get_specials": (
        "Hmm, our specials aren't loading — give us a call back in a few minutes "
        "or I can take a message."
    ),
    "take_message": (
        "I couldn't write that down on our end, sorry. "
        "Please try again in a moment, or call back later."
    ),
    "request_transfer": (
        "I can't reach the owner right now. "
        "Want me to grab a message instead and they'll call you back?"
    ),
    "send_order_link": (
        "I couldn't send that link via text just now. "
        "Want me to take a message instead?"
    ),
    "send_location_link": (
        "I couldn't send the location via text just now. "
        "I can describe how to get here, or take a message."
    ),
}


async def handle_tool_call(
    name: str,
    args: dict[str, Any],
    *,
    api: ApiClient,
    call_sid: str,
    from_phone: str = "",
) -> str:
    fallback = _FALLBACKS.get(name)

    if name == "get_pickup_today":
        return await safe_call(api.get_pickup_today, voice_fallback=fallback)
    if name == "search_menu":
        query = args.get("query", "")
        return await safe_call(lambda: api.search_menu(query), voice_fallback=fallback)
    if name == "list_full_menu":
        category = args.get("category")
        return await safe_call(lambda: api.list_full_menu(category=category), voice_fallback=fallback)
    if name == "list_menu_categories":
        return await safe_call(api.list_menu_categories, voice_fallback=fallback)
    if name == "get_specials":
        return await safe_call(api.get_specials, voice_fallback=fallback)

    if name == "send_order_link":
        # Pre-check: no phone → short-circuit (NOT an error, no fallback)
        if not from_phone:
            return json.dumps(
                {"error": "no caller phone; ask for their number and use take_message"}
            )
        return await safe_call(
            lambda: api.send_sms_link(call_sid=call_sid, to=from_phone, kind="order"),
            voice_fallback=fallback,
        )
    if name == "send_location_link":
        if not from_phone:
            return json.dumps({"error": "no caller phone; ask for their number"})
        return await safe_call(
            lambda: api.send_sms_link(call_sid=call_sid, to=from_phone, kind="location"),
            voice_fallback=fallback,
        )

    if name == "take_message":
        return await safe_call(
            lambda: api.take_message(
                call_sid=call_sid,
                callback_number=args["callback_number"],
                reason=args["reason"],
                caller_name=args.get("caller_name"),
            ),
            voice_fallback=fallback,
        )
    if name == "request_transfer":
        return await safe_call(
            lambda: api.request_transfer(call_sid=call_sid, reason=args.get("reason")),
            voice_fallback=fallback,
        )
    return error_payload(f"unknown tool: {name}")
