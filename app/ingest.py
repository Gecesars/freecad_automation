from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.rag_store import LocalRagStore
from app.settings import CHUNKS_FILE, DOCS_DIR, SOURCES_FILE
from app.utils import ensure_dir, slugify


@dataclass(frozen=True)
class KnowledgeSource:
    title: str
    url: str
    tags: tuple[str, ...]


DEFAULT_SOURCES = [
    {
        "title": "Python scripting tutorial",
        "url": "https://wiki.freecad.org/Python_scripting_tutorial",
        "tags": ["python", "scripting", "macro"],
    },
    {
        "title": "FreeCAD scripting basics",
        "url": "https://wiki.freecad.org/FreeCAD_Scripting_Basics",
        "tags": ["python", "document", "macro"],
    },
    {
        "title": "Topological data scripting",
        "url": "https://wiki.freecad.org/Topological_data_scripting",
        "tags": ["part", "shape", "topology"],
    },
    {
        "title": "Part scripting",
        "url": "https://wiki.freecad.org/Part_scripting",
        "tags": ["part", "geometry", "solid"],
    },
    {
        "title": "Part Workbench",
        "url": "https://wiki.freecad.org/Part_Workbench",
        "tags": ["part", "boolean", "cut", "fuse"],
    },
    {
        "title": "PartDesign Workbench",
        "url": "https://wiki.freecad.org/PartDesign_Workbench",
        "tags": ["partdesign", "features", "sketch"],
    },
    {
        "title": "Sketcher Workbench",
        "url": "https://wiki.freecad.org/Sketcher_Workbench",
        "tags": ["sketcher", "constraints"],
    },
    {
        "title": "Basic Part Design Tutorial",
        "url": "https://wiki.freecad.org/Basic_Part_Design_Tutorial",
        "tags": ["tutorial", "partdesign"],
    },
    {
        "title": "Mesh scripting",
        "url": "https://wiki.freecad.org/Mesh_Scripting",
        "tags": ["mesh", "stl", "export"],
    },
    {
        "title": "Macros",
        "url": "https://wiki.freecad.org/Macros",
        "tags": ["macro", "automation"],
    },
    {
        "title": "Scripted objects",
        "url": "https://wiki.freecad.org/Scripted_objects",
        "tags": ["parametric", "objects"],
    },
    {
        "title": "Start up and configuration",
        "url": "https://wiki.freecad.org/Start_up_and_Configuration",
        "tags": ["command line", "configuration"],
    },
    {
        "title": "Import Export",
        "url": "https://wiki.freecad.org/Import_Export",
        "tags": ["step", "stl", "export"],
    },
    {
        "title": "Part API SourceDoc",
        "url": "https://freecad.github.io/SourceDoc/d2/db9/namespacePart.html",
        "tags": ["api", "part", "reference"],
    },
]


def ensure_sources_file(path: Path = SOURCES_FILE) -> Path:
    if not path.exists():
        ensure_dir(path.parent)
        path.write_text(json.dumps(DEFAULT_SOURCES, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_sources(path: Path = SOURCES_FILE) -> list[KnowledgeSource]:
    ensure_sources_file(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        KnowledgeSource(
            title=item["title"],
            url=item["url"],
            tags=tuple(item.get("tags", [])),
        )
        for item in payload
    ]


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    skip_prefixes = (
        "Retrieved from",
        "This page was last edited",
        "Privacy policy",
        "About FreeCAD Documentation",
        "Disclaimers",
    )
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if any(line.startswith(prefix) for prefix in skip_prefixes):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def html_to_text(html: str, url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for selector in (
        "script",
        "style",
        "noscript",
        "header",
        "footer",
        "nav",
        ".mw-editsection",
        ".toc",
        ".navbox",
        ".metadata",
        ".printfooter",
    ):
        for node in soup.select(selector):
            node.decompose()
    main = (
        soup.select_one("#mw-content-text .mw-parser-output")
        or soup.select_one("main")
        or soup.select_one("article")
        or soup.body
        or soup
    )
    for heading in main.find_all(re.compile("^h[1-6]$")):
        heading.insert_before("\n\n")
        heading.insert_after("\n")
    for pre in main.find_all("pre"):
        pre.insert_before("\n")
        pre.insert_after("\n")
    for br in main.find_all("br"):
        br.replace_with("\n")
    parsed = urlparse(url)
    title = soup.find("h1")
    prefix = f"{title.get_text(' ', strip=True)}\n\n" if title else f"{parsed.netloc}\n\n"
    return _normalize_text(prefix + main.get_text("\n"))


def fetch_source(source: KnowledgeSource, timeout: int = 30) -> str:
    import requests

    response = requests.get(
        source.url,
        headers={
            "User-Agent": "FreeCADPromptForge/0.2 (+local personal knowledge base)",
            "Accept": "text/html, text/plain, application/xhtml+xml",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type or response.text.lstrip().startswith("<"):
        return html_to_text(response.text, source.url)
    return _normalize_text(response.text)


def write_document(source: KnowledgeSource, text: str, docs_dir: Path = DOCS_DIR) -> Path:
    ensure_dir(docs_dir)
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    body = "\n".join(
        [
            f"# {source.title}",
            "",
            f"Source URL: {source.url}",
            f"Fetched UTC: {fetched}",
            f"Tags: {', '.join(source.tags)}",
            "",
            text.strip(),
            "",
        ]
    )
    path = docs_dir / f"{slugify(source.title)}.md"
    path.write_text(body, encoding="utf-8")
    return path


def _read_doc_metadata(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    url = ""
    tags = ""
    for line in text.splitlines()[:12]:
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("Source URL:"):
            url = line.split(":", 1)[1].strip()
        elif line.startswith("Tags:"):
            tags = line.split(":", 1)[1].strip()
    return {"title": title, "url": url, "tags": tags, "text": text}


def chunk_text(text: str, max_chars: int = 1800, overlap_chars: int = 220) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunk = "\n\n".join(current).strip()
            if len(chunk) > 120:
                chunks.append(chunk)
            tail = chunk[-overlap_chars:] if overlap_chars > 0 else ""
            current = [tail] if tail else []
            current_len = len(tail)

    step = max_chars - overlap_chars
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            flush()
            for start in range(0, len(paragraph), step):
                piece = paragraph[start : start + max_chars].strip()
                if len(piece) > 120:
                    chunks.append(piece)
            current = []
            current_len = 0
            continue
        if current_len + len(paragraph) + 2 > max_chars:
            flush()
        current.append(paragraph)
        current_len += len(paragraph) + 2
    flush()
    return chunks


def build_index(docs_dir: Path = DOCS_DIR, chunks_path: Path = CHUNKS_FILE) -> list[dict[str, object]]:
    docs = sorted(docs_dir.glob("*.md"))
    chunks: list[dict[str, object]] = []
    for doc_path in docs:
        metadata = _read_doc_metadata(doc_path)
        for idx, chunk in enumerate(chunk_text(metadata["text"])):
            chunks.append(
                {
                    "id": f"{doc_path.stem}:{idx}",
                    "title": metadata["title"],
                    "url": metadata["url"],
                    "tags": metadata["tags"],
                    "source_file": str(doc_path),
                    "chunk_index": idx,
                    "text": chunk,
                }
            )
    ensure_dir(chunks_path.parent)
    chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    LocalRagStore(chunks_path=chunks_path).rebuild_vectors()
    return chunks


def ingest_sources(sources: Iterable[KnowledgeSource] | None = None) -> list[Path]:
    selected_sources = list(sources or load_sources())
    written: list[Path] = []
    for source in selected_sources:
        text = fetch_source(source)
        written.append(write_document(source, text))
    build_index()
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingere documentacao FreeCAD para a base RAG local.")
    parser.add_argument("--rebuild-only", action="store_true", help="Nao baixa documentos, apenas recria chunks/cache.")
    args = parser.parse_args(argv)
    if args.rebuild_only:
        chunks = build_index()
        print(f"Trechos indexados: {len(chunks)}")
        print(f"Indice: {CHUNKS_FILE}")
        return 0
    written = ingest_sources()
    chunks = json.loads(CHUNKS_FILE.read_text(encoding="utf-8")) if CHUNKS_FILE.exists() else []
    print(f"Documentos coletados: {len(written)}")
    print(f"Trechos indexados: {len(chunks)}")
    print(f"Docs: {DOCS_DIR}")
    print(f"Indice: {CHUNKS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
