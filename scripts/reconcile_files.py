"""Explicit operator CLI for file cleanup reconciliation.

This command is intentionally not scheduled by the application. It requires the
same private storage root and PostgreSQL database as the serving process.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.infrastructure.storage import LocalStorage
from app.modules.files.service import retry_file_cleanup, scan_orphan_objects


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconcile durable file cleanup intents")
    subparsers = parser.add_subparsers(dest="command", required=True)
    retry = subparsers.add_parser("retry-cleanup", help="Claim and retry cleanup jobs")
    retry.add_argument("--limit", type=int, default=100)
    retry.add_argument("--lease-seconds", type=int, default=300)
    scan = subparsers.add_parser(
        "scan-orphans",
        help="Report orphan objects; --apply writes durable cleanup intents",
    )
    scan.add_argument("--grace-seconds", type=int, default=3600)
    scan.add_argument("--apply", action="store_true")
    return parser


async def _run(
    args: argparse.Namespace, database_url: str, storage: LocalStorage
) -> dict[str, object]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            if args.command == "retry-cleanup":
                completed, failed = await retry_file_cleanup(
                    db,
                    storage,
                    limit=args.limit,
                    lease_seconds=args.lease_seconds,
                )
                return {"completed": completed, "failed": failed}
            scanned, orphans, queued = await scan_orphan_objects(
                db,
                storage,
                grace_seconds=args.grace_seconds,
                apply=args.apply,
            )
            return {
                "scanned": scanned,
                "orphans": orphans,
                "queued": queued,
                "applied": bool(args.apply),
            }
    finally:
        await engine.dispose()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url:
        parser.error("DATABASE_URL is required")
    storage = LocalStorage(
        Path(settings.file_storage_root),
        max_bytes=settings.file_max_bytes,
    )
    storage.initialize()
    result = asyncio.run(_run(args, settings.database_url, storage))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
