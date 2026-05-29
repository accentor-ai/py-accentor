from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from accentor.record.observe.sinks import JsonValue, json_safe


class JsonlSink:
    """Write one JSON task event per line to an events.jsonl file."""

    def __init__(
        self,
        path: str | Path,
        *,
        filename: str = "events.jsonl",
        mode: str = "w",
        encoding: str = "utf-8",
        ensure_ascii: bool = False,
    ) -> None:
        target = Path(path)
        if target.suffix != ".jsonl":
            target = target / filename
        self.path = target
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open(mode, encoding=encoding)
        self._ensure_ascii = ensure_ascii
        self._closed = False

    def emit(self, event: Mapping[str, Any]) -> None:
        if self._closed:
            raise ValueError("cannot emit to a closed JsonlSink")
        json_event = json_safe(event)
        if not isinstance(json_event, dict):
            raise TypeError("JSONL events must be JSON objects")
        line = json.dumps(
            json_event,
            ensure_ascii=self._ensure_ascii,
            separators=(",", ":"),
            sort_keys=True,
        )
        self._file.write(f"{line}\n")

    def flush(self) -> None:
        if not self._closed:
            self._file.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._file.flush()
        self._file.close()
        self._closed = True

    def __enter__(self) -> "JsonlSink":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


__all__ = ["JsonlSink"]
