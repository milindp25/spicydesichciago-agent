"""Unit tests for OutcomeTracker."""

from __future__ import annotations

from app.outcome_tracker import OutcomeTracker


def test_empty_tracker_returns_resolved() -> None:
    assert OutcomeTracker().final_outcome() == "resolved"


def test_take_message_success_returns_message_taken() -> None:
    t = OutcomeTracker()
    t.record_tool("take_message", success=True)
    assert t.final_outcome() == "messageTaken"


def test_request_transfer_success_returns_transferred() -> None:
    t = OutcomeTracker()
    t.record_tool("request_transfer", success=True)
    assert t.final_outcome() == "transferred"


def test_request_transfer_failure_only_returns_failed() -> None:
    t = OutcomeTracker()
    t.record_tool("request_transfer", success=False)
    assert t.final_outcome() == "failed"


def test_take_message_then_transfer_returns_transferred() -> None:
    """Last significant tool wins."""
    t = OutcomeTracker()
    t.record_tool("take_message", success=True)
    t.record_tool("request_transfer", success=True)
    assert t.final_outcome() == "transferred"


def test_transfer_failure_then_take_message_returns_message_taken() -> None:
    """Later success overrides earlier failure."""
    t = OutcomeTracker()
    t.record_tool("request_transfer", success=False)
    t.record_tool("take_message", success=True)
    assert t.final_outcome() == "messageTaken"


def test_non_significant_tool_only_returns_resolved() -> None:
    t = OutcomeTracker()
    t.record_tool("search_menu", success=True)
    assert t.final_outcome() == "resolved"


def test_transfer_success_then_transfer_failure_returns_failed() -> None:
    """Last-wins even when the same tool reports both states."""
    t = OutcomeTracker()
    t.record_tool("request_transfer", success=True)
    t.record_tool("request_transfer", success=False)
    assert t.final_outcome() == "failed"
