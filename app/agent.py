from __future__ import annotations

from pathlib import Path

from app.geometry_validator import apply_geometry_autocorrection
from app.macro_generator import MacroGenerator
from app.models import GeneratedDesign, PartSpec
from app.prompt_parser import parse_prompt
from app.rag_query import build_technical_rag_query
from app.rag_store import LocalRagStore
from app.settings import MACROS_DIR, OUTPUT_DIR


class PromptAgent:
    def __init__(
        self,
        rag: LocalRagStore | None = None,
        macros_dir: Path = MACROS_DIR,
        output_dir: Path = OUTPUT_DIR,
        auto_correct_geometry: bool = True,
    ) -> None:
        self.rag = rag or LocalRagStore()
        self.generator = MacroGenerator(macros_dir=macros_dir, output_dir=output_dir)
        self.auto_correct_geometry = auto_correct_geometry

    def parse(self, prompt: str) -> PartSpec:
        return parse_prompt(prompt)

    def generate(self, prompt: str) -> GeneratedDesign:
        spec = self.parse(prompt)
        spec, validation = apply_geometry_autocorrection(spec, auto_correct=self.auto_correct_geometry)
        if not validation.get("valid"):
            raise ValueError(str(validation.get("message", "Geometria invalida.")))
        technical_query = build_technical_rag_query(spec)
        results = tuple(self.rag.search(technical_query, limit=5, technical=True))
        return self.generator.generate(spec, results)
