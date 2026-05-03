from __future__ import annotations

from typing import Any

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_pickup_today",
            "description": (
                "Get today's active pickup location for the food truck — name, address, "
                "hours, and a speakable summary you should read verbatim."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_menu",
            "description": (
                "Search the menu for items matching the caller's query "
                "(e.g., 'chaat', 'momos', 'paneer')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Item name or keyword"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_specials",
            "description": "Get today's specials — items the food truck is featuring.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_message",
            "description": (
                "Save a message for the owner to call back. Use when caller wants to "
                "reach the owner but the owner is unavailable, or when caller has a "
                "complaint/catering request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "callback_number": {
                        "type": "string",
                        "description": "Caller's phone number, E.164 format",
                    },
                    "reason": {"type": "string", "description": "Why they're calling"},
                    "caller_name": {
                        "type": "string",
                        "description": "Caller's name if given",
                    },
                },
                "required": ["callback_number", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_transfer",
            "description": (
                "Transfer the caller to the owner. The system decides: if owner is "
                "available, transfers the live call; if not, returns instruction to "
                "take a message instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why the caller wants the owner",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]
