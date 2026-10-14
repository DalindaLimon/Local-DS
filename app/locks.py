"""Track video files that are being downloaded or streamed so cleanup never touches them."""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager

# A video that was streamed within this many seconds counts as "in use": phones issue
# many short Range requests, so the gap between two requests must not look idle.
STREAM_GRACE_SECONDS = 180


class FileGuard:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._streams: Counter[str] = Counter()
        self._last_stream: dict[str, float] = {}
        self._downloads: set[str] = set()

    @contextmanager
    def streaming(self, video_id: str) -> Iterator[None]:
        with self._lock:
            self._streams[video_id] += 1
            self._last_stream[video_id] = time.time()
        try:
            yield
        finally:
            with self._lock:
                self._streams[video_id] -= 1
                if self._streams[video_id] <= 0:
                    del self._streams[video_id]
                self._last_stream[video_id] = time.time()

    @contextmanager
    def downloading(self, video_id: str) -> Iterator[None]:
        with self._lock:
            self._downloads.add(video_id)
        try:
            yield
        finally:
            with self._lock:
                self._downloads.discard(video_id)

    def busy(self, video_id: str) -> bool:
        with self._lock:
            if self._streams.get(video_id, 0) > 0 or video_id in self._downloads:
                return True
            last = self._last_stream.get(video_id)
            if last and time.time() - last < STREAM_GRACE_SECONDS:
                return True
            self._last_stream.pop(video_id, None)
            return False

    def any_downloading(self) -> bool:
        with self._lock:
            return bool(self._downloads)

    def snapshot(self) -> dict:
        with self._lock:
            return {"streams": dict(self._streams), "downloads": sorted(self._downloads)}

    def reset(self) -> None:
        with self._lock:
            self._streams.clear()
            self._last_stream.clear()
            self._downloads.clear()


guard = FileGuard()
