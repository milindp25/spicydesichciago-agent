from __future__ import annotations

import pytest

from app.intents import is_owner_transfer_request


@pytest.mark.parametrize(
    "text",
    [
        "Connect me to the owner",
        "Can you connect me to the owner?",
        "connect me to your owner please",
        "Please transfer me to the owner",
        "transfer me",
        "I want to speak to the owner",
        "I wanna talk to a human",
        "Speak to a manager",
        "Talk to the manager please",
        "Get me through to the owner",
        "Patch me through to a real person",
        "I need to speak with someone in charge",
    ],
)
def test_owner_intent_matches(text: str) -> None:
    assert is_owner_transfer_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Does the owner have a special menu?",
        "What does the manager recommend?",
        "I called earlier and spoke to someone",
        "Do you have momos?",
        "Can I order biryani?",
        "Where are you located?",
        "",
        "Hello?",
    ],
)
def test_owner_intent_no_false_positives(text: str) -> None:
    assert not is_owner_transfer_request(text)
