from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Feature:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PartSpec:
    prompt: str
    part_type: str
    dimensions: dict[str, float]
    features: tuple[Feature, ...] = ()
    material: str | None = None
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def feature_names(self) -> tuple[str, ...]:
        return tuple(feature.kind for feature in self.features)

    def feature(self, kind: str) -> Feature | None:
        aliases = {
            "holes": ("holes", "bolt_circle_holes"),
            "bolt_circle_holes": ("bolt_circle_holes", "holes"),
        }.get(kind, (kind,))
        for feature in self.features:
            if feature.kind in aliases:
                return feature
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_type": self.part_type,
            "dimensions": self.dimensions,
            "features": [
                {"kind": feature.kind, "params": feature.params}
                for feature in self.features
            ],
            "material": self.material,
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    text: str
    score: float
    source_file: str
    chunk_index: int


@dataclass(frozen=True)
class GeneratedDesign:
    prompt: str
    spec: PartSpec
    macro_code: str
    macro_path: Path
    output_paths: dict[str, Path]
    rag_results: tuple[SearchResult, ...]
    summary: str
    llm_used: bool = False
    llm_model: str | None = None
    llm_notes: str = ""


@dataclass(frozen=True)
class RunResult:
    ok: bool
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    message: str
    mode: str = ""
    output_paths: dict[str, Path] = field(default_factory=dict)
    attempts: tuple[dict[str, Any], ...] = ()
