"""Explicit foreground worker for generated DOCX/PPTX tasks."""

import argparse
import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.document_generations import cleanup_expired, process_due
from app.services.generated_document_deletion import (
    process_document_deletion_jobs,
    reconcile_orphaned_generated_documents,
)


async def _run(limit: int) -> None:
    async with SessionLocal() as db:
        completed, failed = await process_due(db, limit=limit)
        expired = await cleanup_expired(db, limit=max(limit, 20))
        orphaned = await reconcile_orphaned_generated_documents(
            db,
            older_than=datetime.now(UTC)
            - timedelta(hours=get_settings().document_generation_orphan_hours),
        )
        deletions = await process_document_deletion_jobs(db, limit=max(limit, 20))
    print(
        "document worker: "
        f"completed={completed} failed={failed} expired={expired} orphaned={orphaned} "
        f"deleted={deletions.completed} retrying={deletions.retrying}"
    )


async def _watch(limit: int, interval_seconds: float) -> None:
    while True:
        await _run(limit)
        await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run queued document generation work in the foreground"
    )
    parser.add_argument("--limit", type=int, default=10)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="process one batch and exit (default)",
    )
    mode.add_argument(
        "--watch",
        action="store_true",
        help="keep polling in this foreground terminal until Ctrl+C",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=3.0,
        help="poll interval for --watch (minimum 0.5 seconds)",
    )
    args = parser.parse_args()
    limit = max(1, min(args.limit, 100))
    if args.watch:
        interval_seconds = max(0.5, min(args.interval_seconds, 60.0))
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(_watch(limit, interval_seconds))
        return
    asyncio.run(_run(limit))


if __name__ == "__main__":
    main()
