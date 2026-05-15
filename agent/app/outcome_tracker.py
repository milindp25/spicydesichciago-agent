"""Track tool calls during a conversation to derive the final call outcome.

The agent calls multiple tools during a single call. The "outcome" reported
to the API on call end should reflect the last *significant* tool result:

- ``request_transfer`` success -> ``"transferred"``
- ``take_message`` success     -> ``"messageTaken"``
- ``request_transfer`` failure -> ``"failed"`` (unless a later success overrides)
- anything else / nothing      -> ``"resolved"``

Last-significant-wins: if the caller takes a message and then transfers, the
outcome is ``"transferred"``. If a transfer fails and then a message is
taken, the outcome is ``"messageTaken"``.
"""

from __future__ import annotations

# Tools whose result determines the call outcome. Other tools (search_menu,
# get_hours, list_categories, etc.) don't change the outcome.
_SIGNIFICANT_TOOLS = frozenset({"request_transfer", "take_message"})

_SUCCESS_OUTCOME = {
    "request_transfer": "transferred",
    "take_message": "messageTaken",
}


class OutcomeTracker:
    """Records significant tool calls and computes a final outcome string."""

    def __init__(self) -> None:
        # Latest significant tool call seen, as (name, success). ``None`` until
        # a significant tool has been recorded.
        self._last: tuple[str, bool] | None = None

    def record_tool(self, name: str, *, success: bool) -> None:
        """Record a tool call. Non-significant tools are ignored."""
        if name not in _SIGNIFICANT_TOOLS:
            return
        self._last = (name, success)

    def final_outcome(self) -> str:
        """Return the wire-value outcome for this call."""
        if self._last is None:
            return "resolved"
        name, success = self._last
        if not success:
            return "failed"
        return _SUCCESS_OUTCOME.get(name, "resolved")
