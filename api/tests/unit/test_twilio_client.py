from app.infrastructure.twilio_client import NoopTwilioClient


async def test_noop_send_sms_returns_false() -> None:
    c = NoopTwilioClient()
    assert await c.send_sms(to="+15555550100", body="hi") is False


async def test_noop_redirect_call_returns_false() -> None:
    c = NoopTwilioClient()
    assert await c.redirect_call(call_sid="CA1", twiml_url="https://x") is False
