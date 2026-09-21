"""Run medical image retention cleanup: python -m app.image_cleanup_cli [--dry-run]."""

from __future__ import annotations

import argparse
import asyncio

from app.db.session import SessionLocal
from app.services.medical_image_cleanup import cleanup_medical_images


async def _run(dry_run: bool) -> None:
    async with SessionLocal() as db:
        result = await cleanup_medical_images(db, dry_run=dry_run)
    print(
        f"lock_acquired={result.lock_acquired} "
        f"expired={result.expired} orphaned={result.orphaned} dry_run={dry_run}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    main()