from __future__ import annotations

import json
from typing import Any

from app.tools.api_client import ApiClient


async def handle_tool_call(
    name: str, args: dict[str, Any], *, api: ApiClient, call_sid: str
) -> str:
    if name == "get_pickup_today":
        return json.dumps(await api.get_pickup_today())
    if name == "search_menu":
        return json.dumps(await api.search_menu(args.get("query", "")))
    if name == "list_full_menu":
        return json.dumps(await api.list_full_menu())
    if name == "get_specials":
        return json.dumps(await api.get_specials())
    if name == "take_message":
        result = await api.take_message(
            call_sid=call_sid,
            callback_number=args["callback_number"],
            reason=args["reason"],
            caller_name=args.get("caller_name"),
        )
        return json.dumps(result)
    if name == "request_transfer":
        result = await api.request_transfer(call_sid=call_sid, reason=args.get("reason"))
        return json.dumps(result)
    return json.dumps({"error": f"unknown tool: {name}"})
