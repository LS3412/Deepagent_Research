"""CLI: ingest a file or folder into Weaviate.

Usage:
    python -m src.ingestion.cli <path> [--tenant default] [--tags tag1,tag2]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.ingestion.pipeline import ingest_directory, ingest_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest unstructured data into Weaviate.")
    ap.add_argument("path", help="File or directory to ingest")
    ap.add_argument("--tenant", default=None, help="Tenant ID (default from .env)")
    ap.add_argument("--tags", default="", help="Comma-separated tags")
    ap.add_argument("--no-recursive", action="store_true", help="Do not recurse into subdirs")
    args = ap.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    p = Path(args.path)
    if not p.exists():
        print(f"path not found: {p}", file=sys.stderr)
        return 2

    if p.is_dir():
        results = ingest_directory(
            p, tenant_id=args.tenant, tags=tags, recursive=not args.no_recursive
        )
    else:
        results = [ingest_path(p, tenant_id=args.tenant, tags=tags)]

    new = sum(r.chunks_indexed for r in results)
    skipped = sum(1 for r in results if r.skipped)
    print(f"\nDone. files={len(results)} new_chunks={new} skipped={skipped}")
    for r in results:
        flag = "SKIP" if r.skipped else "OK  "
        suffix = f" ({r.reason})" if r.reason else ""
        print(f"  {flag} {r.file_name:<60} chunks={r.chunks_indexed}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
