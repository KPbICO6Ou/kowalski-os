"""Watch mode: watchdog Observer over the index roots with a debounced incremental update."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .embedder import Embedder
from .scanner import update_paths
from .store import VectorStore

DEBOUNCE_SECONDS = 2.0


class _CollectingHandler(FileSystemEventHandler):
    """Funnels created/modified/moved/deleted paths into a shared pending set."""

    def __init__(self, pending: set[Path], lock: threading.Lock, stamp: list[float]):
        self._pending = pending
        self._lock = lock
        self._stamp = stamp

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type not in ("created", "modified", "moved", "deleted"):
            return
        paths = [event.src_path]
        if getattr(event, "dest_path", ""):
            paths.append(event.dest_path)
        with self._lock:
            for raw in paths:
                self._pending.add(Path(str(raw)))
            self._stamp[0] = time.monotonic()


class Watcher:
    """Observes the roots and applies batched incremental updates after a quiet period."""

    def __init__(
        self,
        roots: Iterable[Path],
        store: VectorStore,
        embedder: Embedder,
        debounce: float = DEBOUNCE_SECONDS,
    ):
        self.roots = [Path(root).expanduser() for root in roots]
        self.store = store
        self.embedder = embedder
        self.debounce = debounce
        self._pending: set[Path] = set()
        self._lock = threading.Lock()
        self._stamp = [0.0]
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def drain(self) -> set[Path]:
        """Pending paths if the debounce window has elapsed, else an empty set."""
        with self._lock:
            if not self._pending or time.monotonic() - self._stamp[0] < self.debounce:
                return set()
            pending, self._pending = self._pending, set()
            return pending

    def process_pending(self) -> None:
        pending = self.drain()
        if not pending:
            return
        summary = update_paths(pending, self.store, self.embedder)
        if summary.indexed or summary.deleted:
            print(f"[watch] {summary}", flush=True)

    def run(self) -> None:
        """Block watching the roots until stop() or KeyboardInterrupt."""
        observer = Observer()
        handler = _CollectingHandler(self._pending, self._lock, self._stamp)
        for root in self.roots:
            if root.is_dir():
                observer.schedule(handler, str(root), recursive=True)
        observer.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
                self.process_pending()
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()
