"""Admin CLI for one-off operations the owner runs daily.

Usage:
    python3 -m app.admin pickup [--tenant spicy-desi]

Lists Square locations, prompts you to pick today's active pickup spot, and saves
the choice to data/pickup-state.json.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.infrastructure.cache import TtlCache  # noqa: E402
from app.infrastructure.config import AppSettings  # noqa: E402
from app.infrastructure.pickup_state import PickupStateStore  # noqa: E402
from app.infrastructure.square_client import (  # noqa: E402
    SquareLocationsAdapter,
    make_square_client,
)
from app.services.locations_service import LocationsService  # noqa: E402
from app.services.pickup_service import PickupService  # noqa: E402


async def _run_pickup(tenant: str) -> int:
    settings = AppSettings()
    sq_client = make_square_client(
        access_token=settings.square_access_token,
        environment=settings.square_environment,
    )
    locations_service = LocationsService(
        api=SquareLocationsAdapter(sq_client),
        cache=TtlCache(ttl_seconds=60),
    )
    pickup_service = PickupService(
        store=PickupStateStore("./data/pickup-state.json"),
        locations=locations_service,
    )

    locations = await locations_service.list_locations()
    if not locations:
        print("No Square locations returned. Check your access token.", file=sys.stderr)
        return 1

    print(f"\nSelect today's active pickup location for '{tenant}':\n")
    for idx, loc in enumerate(locations, start=1):
        print(f"  {idx}. {loc.name}  —  {loc.address}  ({loc.location_id})")
    print()

    while True:
        raw = input(f"Pick 1-{len(locations)} (or q to quit): ").strip().lower()
        if raw in {"q", "quit", "exit"}:
            return 0
        try:
            idx = int(raw)
        except ValueError:
            print("  not a number")
            continue
        if not 1 <= idx <= len(locations):
            print(f"  out of range (1-{len(locations)})")
            continue
        chosen = locations[idx - 1]
        break

    record = await pickup_service.set_today(tenant, chosen.location_id)
    print(f"\n✓ Set today's pickup for '{tenant}' to: {chosen.name}")
    print(f"  location_id: {record.location_id}")
    print(f"  set_at:      {record.set_at}")
    print(f"  set_for:     {record.set_for_date}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pickup", help="Set today's active pickup location")
    p.add_argument("--tenant", default="spicy-desi")
    args = parser.parse_args()
    if args.cmd == "pickup":
        return asyncio.run(_run_pickup(args.tenant))
    return 1


if __name__ == "__main__":
    sys.exit(main())
