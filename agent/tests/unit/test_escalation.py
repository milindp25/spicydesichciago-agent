from __future__ import annotations

import pytest

from app.escalation import decode_chain, encode_chain, pop_head


def test_encode_decode_roundtrip() -> None:
    contacts = [
        {"phone": "+13125550100", "timeout_seconds": 25, "label": "manager"},
        {"phone": "+13125550101", "timeout_seconds": 30, "label": "kitchen"},
    ]
    encoded = encode_chain(contacts)
    assert isinstance(encoded, str) and encoded
    assert decode_chain(encoded) == contacts


def test_encode_empty_returns_empty_string() -> None:
    assert encode_chain([]) == ""


def test_decode_none_returns_empty_list() -> None:
    assert decode_chain(None) == []


def test_decode_empty_string_returns_empty_list() -> None:
    assert decode_chain("") == []


def test_decode_garbage_returns_empty_list() -> None:
    assert decode_chain("not-valid-base64!@#$") == []
    # Valid base64 but invalid JSON
    assert decode_chain("Zm9vYmFy") == []  # "foobar"


def test_pop_head_on_empty() -> None:
    head, tail = pop_head([])
    assert head is None
    assert tail == []


def test_pop_head_on_non_empty() -> None:
    contacts = [
        {"phone": "+1", "timeout_seconds": 25, "label": "a"},
        {"phone": "+2", "timeout_seconds": 30, "label": "b"},
    ]
    head, tail = pop_head(contacts)
    assert head == {"phone": "+1", "timeout_seconds": 25, "label": "a"}
    assert tail == [{"phone": "+2", "timeout_seconds": 30, "label": "b"}]
    # Original list is not mutated.
    assert len(contacts) == 2


def test_encode_rejects_contact_without_phone() -> None:
    with pytest.raises(ValueError, match="phone"):
        encode_chain([{"timeout_seconds": 25}])


def test_encode_rejects_contact_without_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        encode_chain([{"phone": "+1"}])


def test_decode_skips_malformed_entries() -> None:
    # Manually craft a chain with a mix of good and bad entries.
    import base64
    import json

    raw = json.dumps(
        [
            {"phone": "+1", "timeout_seconds": 25, "label": "ok"},
            {"timeout_seconds": 25},  # missing phone -> skipped
            "not-a-dict",  # skipped
            {"phone": "+2", "timeout_seconds": 30},  # no label is fine
        ]
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    out = decode_chain(encoded)
    assert len(out) == 2
    assert out[0]["phone"] == "+1"
    assert out[1]["phone"] == "+2"
    assert out[1]["label"] == ""
