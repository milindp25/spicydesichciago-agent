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
            "name": "list_menu_categories",
            "description": (
                "List the menu categories with how many items are in each. "
                "Compact — use this FIRST for open questions like 'what's on the menu?' "
                "so you can read off the categories instead of dumping every item."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_full_menu",
            "description": (
                "List menu items. Pass a category (e.g. 'Chaat', 'Mains', 'Drinks') "
                "to get only that category — preferred. Without a category it returns "
                "the entire menu, which is large; only do that as a last resort."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category filter, case-insensitive",
                    },
                },
                "required": [],
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
            "name": "send_order_link",
            "description": (
                "Text the caller a link to place an order online. Use this when the caller "
                "wants to order food (we don't take phone orders). Sends to their caller ID."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_location_link",
            "description": (
                "Text the caller today's pickup address with a Google Maps link. Use this "
                "when the caller asks 'where are you?' or wants directions. Sends to caller ID."
            ),
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
