def test_bot_module_imports() -> None:
    from app import bot

    assert callable(bot.run_bot)
    assert callable(bot.load_system_prompt)


def test_system_prompt_contains_greeting() -> None:
    from app.bot import load_system_prompt

    prompt = load_system_prompt()
    assert "Spicy Desi" in prompt
    # Loose check that there's a phone-style greeting line — wording can vary.
    assert "what can i get" in prompt.lower() or "how can i help" in prompt.lower()


def test_format_caller_history_first_time() -> None:
    from app.bot import _format_caller_history

    assert _format_caller_history({"is_returning": False}) == "First-time caller."


def test_format_caller_history_returning_includes_summaries() -> None:
    from app.bot import _format_caller_history

    note = _format_caller_history(
        {
            "is_returning": True,
            "call_count": 3,
            "events": [
                {"summary": "asked about catering"},
                {"summary": "left message about veg options"},
            ],
        }
    )
    assert "Returning caller" in note
    assert "catering" in note
    assert "veg options" in note


def test_build_call_context_includes_after_hours_warning_when_owner_unavailable() -> None:
    from app.bot import _build_call_context

    msg = _build_call_context(
        history_note="First-time caller.",
        from_phone="+13125551234",
        owner_available=False,
        greeting="Hey, Spicy Desi",
    )
    assert "OUTSIDE business hours" in msg
    assert "DO NOT call request_transfer" in msg
    assert "Hey, Spicy Desi" in msg


def test_build_call_context_owner_available_no_warning() -> None:
    from app.bot import _build_call_context

    msg = _build_call_context(
        history_note="First-time caller.",
        from_phone="",
        owner_available=True,
        greeting="",
    )
    assert "OUTSIDE business hours" not in msg
    assert "unknown" in msg  # phone fallback


def test_coerce_tool_args_handles_none_string_dict() -> None:
    from app.bot import _coerce_tool_args

    assert _coerce_tool_args(None) == {}
    assert _coerce_tool_args("") == {}
    assert _coerce_tool_args('{"a": 1}') == {"a": 1}
    assert _coerce_tool_args("not-json") == {}
    assert _coerce_tool_args({"x": 2}) == {"x": 2}
    # JSON that isn't an object falls back to empty.
    assert _coerce_tool_args("[1, 2]") == {}
