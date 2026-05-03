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
