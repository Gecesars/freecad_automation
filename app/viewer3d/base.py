from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ViewerStatus:
    mode: str
    ok: bool
    message: str
    loaded_path: Path | None = None
