from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any


def resolve_path(raw_path: str | None, default_path: Path) -> Path:
    if raw_path and raw_path.strip():
        return Path(raw_path).expanduser().resolve()
    return default_path


def list_directory(path: Path, include_hidden: bool = False) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if not include_hidden and entry.name.startswith("."):
            continue
        stat = entry.stat()
        items.append(
            {
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )
    return items


def read_text_file(path: Path, max_bytes: int) -> str:
    with path.open("rb") as fh:
        raw = fh.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    return raw.decode("utf-8", errors="replace")


def tail_text_file(path: Path, lines: int, max_bytes: int) -> str:
    lines = max(1, min(lines, 5000))
    with path.open("rb") as fh:
        raw = fh.read(max_bytes)
    text = raw.decode("utf-8", errors="replace")
    dq: deque[str] = deque(maxlen=lines)
    for line in text.splitlines():
        dq.append(line)
    return "\n".join(dq)
