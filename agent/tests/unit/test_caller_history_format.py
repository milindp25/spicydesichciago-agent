"""Unit tests for _format_caller_history.

The function lives in app.bot and renders the JSON returned by
/api/callers/history into a short bullet list for the LLM system context.
"""
from __future__ import annotations

from app.bot import _format_caller_history


def test_first_time_caller() -> None:
    out = _format_caller_history({"is_returning": False, "call_count": 0, "events": []})
    assert out == "First-time caller."


def test_returning_caller_full_context() -> None:
    history = {
        "is_returning": True,
        "call_count": 4,
        "events": [],
        "last_summary": "Asked about catering pricing for Saturday; took a message.",
        "last_message_reason": "catering for Saturday",
        "last_message_pending": True,
        "last_sms_kind": "order",
        "recent_menu_queries": ["samosa", "biryani"],
    }
    out = _format_caller_history(history)
    assert "4 prior call(s)" in out
    assert "Last call: Asked about catering pricing" in out
    assert 'Pending: last message ("catering for Saturday") still unhandled.' in out
    assert "SMS we sent last: order link." in out
    assert "Previously asked about: samosa, biryani." in out


def test_pending_false_with_reason() -> None:
    history = {
        "is_returning": True,
        "call_count": 2,
        "events": [],
        "last_summary": None,
        "last_message_reason": "follow up",
        "last_message_pending": False,
        "last_sms_kind": None,
        "recent_menu_queries": [],
    }
    out = _format_caller_history(history)
    assert 'Previous message ("follow up") has been handled.' in out
    assert "Pending" not in out


def test_minimal_returning_caller_falls_back_to_legacy_events() -> None:
    history = {
        "is_returning": True,
        "call_count": 1,
        "events": [{"kind": "callStarted", "summary": "Called previously"}],
        "last_summary": None,
        "last_message_reason": None,
        "last_message_pending": None,
        "last_sms_kind": None,
        "recent_menu_queries": [],
    }
    out = _format_caller_history(history)
    assert "1 prior call(s)" in out
    assert "- Called previously" in out


def test_minimal_returning_caller_no_events_no_rich_fields() -> None:
    history = {
        "is_returning": True,
        "call_count": 1,
        "events": [],
    }
    out = _format_caller_history(history)
    assert "1 prior call(s)" in out


def test_skips_empty_fields() -> None:
    history = {
        "is_returning": True,
        "call_count": 3,
        "events": [],
        "last_summary": "",
        "last_message_reason": None,
        "last_message_pending": None,
        "last_sms_kind": "location",
        "recent_menu_queries": [],
    }
    out = _format_caller_history(history)
    # Only the SMS line should be present.
    assert "SMS we sent last: location link." in out
    assert "Last call" not in out
    assert "Pending" not in out
    assert "Previously asked" not in out
