from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.settings import DIAGNOSTICS_DIR


def write_runtime_report(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = path or (DIAGNOSTICS_DIR / "runtime_report.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": datetime.now().isoformat(timespec="seconds"), **payload}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
