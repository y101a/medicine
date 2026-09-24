"""Resume asynchronous image tasks and expire retained generated images."""

from __future__ import annotations

import argparse
import asyncio

from app.db.session import SessionLocal
from app.services.image_generations import cleanup_expired, process_due


async def _run(limit: int) -> None:
    async with SessionLocal() as db:
        completed, failed = await process_due(db, limit=limit)
        expired = await cleanup_expired(db, limit=max(limit, 200))
    print(f"completed={completed} failed={failed} expired={expired}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(_run(max(1, min(args.limit, 200))))


if __name__ == "__main__":
    main()
