from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.domain.models import EventRecord


class JsonlEventLog:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    async def append(self, event: EventRecord) -> None:
        record = event.model_copy(update={"ts": event.ts or time.time()})
        line = json.dumps(record.model_dump(), separators=(",", ":")) + "\n"
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
