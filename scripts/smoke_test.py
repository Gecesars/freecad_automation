#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import PromptAgent
from app.rag_store import LocalRagStore


def main() -> int:
    prompt = "Crie uma placa de aluminio 120x80x6 mm com quatro furos de 6 mm nos cantos e um rasgo central de 40x12 mm."
    design = PromptAgent(LocalRagStore()).generate(prompt)
    print(design.summary)
    print()
    print(f"Macro: {design.macro_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
