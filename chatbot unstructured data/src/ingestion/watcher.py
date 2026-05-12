"""Watched-folder ingester.

Drops new/modified files into the pipeline. Single-process for v1; the same
pattern can be swapped for a Redis-Streams-backed consumer pool later without
changing the pipeline.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Lock, Timer

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.config import get_settings
from src.ingestion.pipeline import ingest_path

log = logging.getLogger(__name__)


class _DebouncedHandler(FileSystemEventHandler):
    def __init__(self, debounce_seconds: float = 2.0) -> None:
        self._timers: dict[str, Timer] = {}
        self._lock = Lock()
        self._debounce = debounce_seconds

    def _schedule(self, path: str) -> None:
        with self._lock:
            t = self._timers.pop(path, None)
            if t:
                t.cancel()
            new = Timer(self._debounce, self._fire, args=[path])
            self._timers[path] = new
            new.start()

    def _fire(self, path: str) -> None:
        try:
            log.info("watcher ingesting %s", path)
            res = ingest_path(path)
            log.info(
                "watcher result: %s chunks=%d skipped=%s reason=%s",
                res.file_name, res.chunks_indexed, res.skipped, res.reason,
            )
        except Exception:
            log.exception("watcher failed for %s", path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = get_settings()
    watch = Path(s.watch_dir)
    watch.mkdir(parents=True, exist_ok=True)
    log.info("watching %s", watch.resolve())

    obs = Observer()
    obs.schedule(_DebouncedHandler(), str(watch), recursive=True)
    obs.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()


if __name__ == "__main__":
    main()
