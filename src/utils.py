from __future__ import annotations

import re
from pathlib import Path


def normalize_code(text: str) -> str:
    """Normalize only transport-level differences, not program content.

    Monaco/browser payloads may normalize CRLF to LF and may add/remove a final newline.
    We deliberately do not strip spaces or internal blank lines, so truncation/content changes
    are still detected.
    """
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def safe_slug(text: str, max_len: int = 100) -> str:
    value = re.sub(r"[^0-9A-Za-z._-]+", "_", text or "").strip("._-")
    return (value or "unnamed")[:max_len]


def ensure_parent(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
