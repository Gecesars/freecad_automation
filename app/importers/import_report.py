from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ImportReport:
    ok: bool
    importer: str
    source_path: str
    message: str
    layers: list[str] = field(default_factory=list)
    entity_count: int = 0
    bbox: dict[str, float] = field(default_factory=dict)
    output_paths: dict[str, str] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# Import Report: {self.importer}",
            "",
            f"- OK: {self.ok}",
            f"- Source: `{self.source_path}`",
            f"- Message: {self.message}",
            f"- Entities: {self.entity_count}",
            f"- Layers: {', '.join(self.layers) if self.layers else '(none)'}",
            "",
            "## Bounding Box",
            "```json",
            json.dumps(self.bbox, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Outputs",
        ]
        if self.output_paths:
            lines.extend(f"- {key}: `{value}`" for key, value in self.output_paths.items())
        else:
            lines.append("- No output files.")
        if self.diagnostics:
            lines.extend(["", "## Diagnostics"])
            lines.extend(f"- {item}" for item in self.diagnostics)
        return "\n".join(lines) + "\n"

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".json":
            path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            path.write_text(self.to_markdown(), encoding="utf-8")
        return path
