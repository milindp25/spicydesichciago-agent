from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PickupRecord:
    location_id: str
    set_at: str
    set_for_date: str


class PickupStateStore:
    """Single-file JSON store mapping tenant_slug -> active pickup record.

    Atomic writes via temp file + rename. Lock ensures concurrent writes don't
    interleave within one process.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def get(self, tenant_slug: str) -> PickupRecord | None:
        async with self._lock:
            data = self._read()
        record = data.get(tenant_slug)
        if record is None:
            return None
        return PickupRecord(
            location_id=record["location_id"],
            set_at=record["set_at"],
            set_for_date=record["set_for_date"],
        )

    async def set(self, tenant_slug: str, record: PickupRecord) -> None:
        async with self._lock:
            data = self._read()
            data[tenant_slug] = {
                "location_id": record.location_id,
                "set_at": record.set_at,
                "set_for_date": record.set_for_date,
            }
            self._write(data)

    def _read(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text() or "{}")

    def _write(self, data: dict[str, dict[str, str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self._path)
