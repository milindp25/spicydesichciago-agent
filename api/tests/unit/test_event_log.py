import json
from pathlib import Path

from app.domain.models import EventRecord
from app.infrastructure.event_log import JsonlEventLog


async def test_append_and_iterate(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    log = JsonlEventLog(str(log_path))
    await log.append(EventRecord(call_sid="CA1", kind="call_started", payload={}))
    await log.append(EventRecord(call_sid="CA1", kind="message_taken", payload={"name": "Asha"}))

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["call_sid"] == "CA1"
    assert first["kind"] == "call_started"
    assert "ts" in first


async def test_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "events.jsonl"
    log = JsonlEventLog(str(nested))
    await log.append(EventRecord(call_sid="CA1", kind="x"))
    assert nested.exists()
