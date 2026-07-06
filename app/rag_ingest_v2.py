from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

from app.freecad_runner import find_freecad_executable
from app.rag_index_v2 import V2_CHUNKS_FILE, build_hybrid_index
from app.settings import APP_DIR, DOCS_DIR, RAG_DIR

LOCAL_FREECAD_MOD = Path.home() / ".local" / "share" / "FreeCAD" / "v1-1" / "Mod"
TEXT_EXTENSIONS = {".py", ".md", ".rst", ".txt", ".html", ".ui", ".qss", ".json", ".xml"}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _chunk_text(text: str, max_chars: int = 700, overlap: int = 80) -> list[str]:
    chunks: list[str] = []
    step = max_chars - overlap
    text = text.strip()
    if not text:
        return chunks
    for start in range(0, len(text), step):
        piece = text[start : start + max_chars].strip()
        if len(piece) >= 80:
            chunks.append(piece)
    return chunks


def _domain_for(path: Path, text: str) -> str:
    lower = (str(path) + " " + text[:1000]).lower()
    if any(term in lower for term in ("dxf", "dwg", "svg", "import")):
        return "import"
    if any(term in lower for term in ("export", "step", "stl", "obj", "brep")):
        return "export"
    if any(term in lower for term in ("freecadgui", "pyside", "viewer", "qt")):
        return "viewer"
    if "sketch" in lower:
        return "sketcher"
    if any(term in lower for term in ("part", "makebox", "makecylinder", "shape")):
        return "part"
    return "macro"


def collect_sources() -> list[Path]:
    sources: list[Path] = []
    sources.extend(sorted(DOCS_DIR.glob("*.md")))
    api_dump_dir = RAG_DIR / "api_dump"
    sources.extend(sorted(api_dump_dir.glob("*.md")))
    sources.extend(sorted(api_dump_dir.glob("*.json")))
    if LOCAL_FREECAD_MOD.exists():
        for path in sorted(LOCAL_FREECAD_MOD.rglob("*")):
            if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS and path.stat().st_size <= 2_000_000:
                sources.append(path)
    return sources


def dump_api_if_possible() -> None:
    command = find_freecad_executable()
    script = APP_DIR / "tools" / "dump_freecad_api.py"
    if not command or not script.exists():
        return
    attempts = [[command, "freecadcmd", str(script)], [command, "--console", str(script)]]
    for invocation in attempts:
        try:
            proc = subprocess.run(invocation, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=False)
        except Exception:
            continue
        if proc.returncode == 0 and (RAG_DIR / "api_dump" / "freecad_api_dump.md").exists():
            return


def ingest_v2(run_api_dump: bool = True) -> dict[str, object]:
    if run_api_dump:
        dump_api_if_possible()
    chunks: list[dict[str, object]] = []
    sources = collect_sources()
    for source in sources:
        try:
            text = _read_text(source)
        except Exception:
            continue
        domain = _domain_for(source, text)
        title = source.stem
        url = ""
        if source.is_relative_to(DOCS_DIR):
            for line in text.splitlines()[:8]:
                if line.startswith("# "):
                    title = line[2:].strip()
                elif line.startswith("Source URL:"):
                    url = line.split(":", 1)[1].strip()
        for idx, chunk in enumerate(_chunk_text(text)):
            chunks.append(
                {
                    "id": f"{source}:{idx}",
                    "title": title,
                    "url": url,
                    "tags": domain,
                    "domain": domain,
                    "source_file": str(source),
                    "chunk_index": idx,
                    "text": chunk,
                }
            )
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    V2_CHUNKS_FILE.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    audit = build_hybrid_index(V2_CHUNKS_FILE)
    audit.update(
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_files": len(sources),
            "minimum_required": 25_000,
            "target_met": len(chunks) >= 25_000,
            "note": "" if len(chunks) >= 25_000 else "Corpus local disponivel nao atingiu 25.000 chunks sem duplicar conteudo.",
        }
    )
    (RAG_DIR / "rag_v2_summary.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAG v2 ingestao local FreeCAD.")
    parser.add_argument("--skip-api-dump", action="store_true")
    args = parser.parse_args(argv)
    audit = ingest_v2(run_api_dump=not args.skip_api_dump)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit.get("chunks", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
