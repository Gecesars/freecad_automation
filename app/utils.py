from __future__ import annotations

import re
import unicodedata
from pathlib import Path


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower()


def slugify(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "generated-part"


def format_mm(value: float) -> str:
    if abs(value - round(value)) < 0.0001:
        return str(int(round(value)))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
