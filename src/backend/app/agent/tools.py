"""TOOLS schemas. Must match src/API.md -> "AI tools" exactly (shared with the ML dataset)."""

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "add_item",
            "description": "Add a menu item to the cart. Use only ids from the provided menu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "menu_item_id": {"type": "string", "description": "slug from the menu"},
                    "qty": {"type": "integer", "minimum": 1},
                    "note": {"type": "string"},
                },
                "required": ["menu_item_id", "qty"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_item",
            "description": "Remove a menu item from the cart, or reduce its quantity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "menu_item_id": {"type": "string"},
                    "qty": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "omit to remove completely",
                    },
                },
                "required": ["menu_item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_order_type",
            "description": "Set pickup or delivery.",
            "parameters": {
                "type": "object",
                "properties": {"type": {"type": "string", "enum": ["pickup", "delivery"]}},
                "required": ["type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_address",
            "description": "Save the delivery address the customer typed.",
            "parameters": {
                "type": "object",
                "properties": {"address": {"type": "string"}},
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_payment",
            "description": "Call when the customer has finished choosing. Backend checks the order is complete and sends payment instructions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_paid_by_customer",
            "description": "Call when the customer says they have paid. Does NOT confirm payment.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_owner",
            "description": "Complaint, angry customer, or a question the menu cannot answer.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ignore_or_flag",
            "description": "Message is not about ordering (friend, spam, personal chat). No reply is sent.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]

TOOL_NAMES = [t["function"]["name"] for t in TOOLS]
