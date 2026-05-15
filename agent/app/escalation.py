"""Escalation chain encoding for Twilio TwiML query parameters.

We forward the remaining escalation chain across redirects as a URL-safe
base64-encoded JSON blob. The agent stays stateless on tenant config: the
API encodes the full chain once when issuing the initial redirect, and each
subsequent TwiML hop pops the head and forwards the tail.

Each contact is a dict with at minimum:
    - phone: str (E.164)
    - timeout_seconds: int (Twilio Dial timeout)
    - label: str (optional, human-readable)
"""
from __future__ import annotations

import base64
import json
from typing import Any


def encode_chain(contacts: list[dict[str, Any]]) -> str:
    """Encode a list of escalation contacts as a URL-safe base64 JSON blob.

    Validates each contact has `phone` and `timeout_seconds`. Returns an
    empty string for an empty list (callers can omit the query param).
    """
    if not contacts:
        return ""
    cleaned: list[dict[str, Any]] = []
    for c in contacts:
        if not isinstance(c, dict):
            raise ValueError(f"contact must be a dict, got {type(c).__name__}")
        if not c.get("phone"):
            raise ValueError("contact missing required 'phone'")
        if "timeout_seconds" not in c:
            raise ValueError("contact missing required 'timeout_seconds'")
        cleaned.append({
            "phone": str(c["phone"]),
            "timeout_seconds": int(c["timeout_seconds"]),
            "label": str(c.get("label", "")),
        })
    raw = json.dumps(cleaned, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_chain(encoded: str | None) -> list[dict[str, Any]]:
    """Decode a chain string. Tolerant: None / empty / garbage -> []."""
    if not encoded:
        return []
    try:
        # Restore padding stripped by encode_chain.
        padded = encoded + "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if not item.get("phone") or "timeout_seconds" not in item:
            continue
        out.append({
            "phone": str(item["phone"]),
            "timeout_seconds": int(item["timeout_seconds"]),
            "label": str(item.get("label", "")),
        })
    return out


def pop_head(
    contacts: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return (head, tail). On empty list, returns (None, [])."""
    if not contacts:
        return None, []
    return contacts[0], list(contacts[1:])
