"""Short-lived in-memory cache of extracted document text for sectioned reading.

Entries are keyed by path, Nextcloud ETag and extraction mode, so a changed file never
matches an old entry. The cache is bounded by total size, entry count and age; it lives only
in the process memory (nothing is written to disk) and is lost on restart.
"""

from __future__ import annotations

import sys
import time
from collections import OrderedDict

from .extractors import Extraction

CACHE_MAX_BYTES = 96_000_000
CACHE_MAX_ENTRIES = 8
CACHE_TTL_SECONDS = 600.0

Key = tuple[str, str, bool]


def entry_size(extraction: Extraction) -> int:
    return sys.getsizeof(extraction.text) + 200 * (len(extraction.sections) + len(extraction.notes)) + 1024


class ExtractionCache:
    def __init__(
        self,
        max_bytes: int = CACHE_MAX_BYTES,
        max_entries: int = CACHE_MAX_ENTRIES,
        ttl_seconds: float = CACHE_TTL_SECONDS,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[Key, tuple[float, int, Extraction]] = OrderedDict()
        self.size = 0

    def __len__(self) -> int:
        return len(self._entries)

    def _drop(self, key: Key) -> None:
        _, size, _ = self._entries.pop(key)
        self.size -= size

    def _expire(self) -> None:
        now = time.monotonic()
        for key in [key for key, (stored, _, _) in self._entries.items() if now - stored > self.ttl_seconds]:
            self._drop(key)

    def get(self, key: Key) -> Extraction | None:
        self._expire()
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry[2]

    def put(self, key: Key, extraction: Extraction) -> bool:
        """Store *extraction*; returns False if it is larger than the whole cache."""
        size = entry_size(extraction)
        if key in self._entries:
            self._drop(key)
        # Older versions of the same file are useless once a new ETag was seen.
        for old in [old for old in self._entries if old[0] == key[0] and old[2] == key[2]]:
            self._drop(old)
        if size > self.max_bytes:
            return False
        self._expire()
        while self._entries and (self.size + size > self.max_bytes or len(self._entries) >= self.max_entries):
            self._drop(next(iter(self._entries)))
        self._entries[key] = (time.monotonic(), size, extraction)
        self.size += size
        return True
