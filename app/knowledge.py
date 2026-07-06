from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.settings import CHUNKS_FILE, RAW_KNOWLEDGE_DIR, SOURCES_FILE


@dataclass(frozen=True)
class KnowledgeSource:
    title: str
    url: str
    tags: tuple[str, ...]


def load_sources(path: Path = SOURCES_FILE) -> list[KnowledgeSource]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        KnowledgeSource(
            title=item["title"],
            url=item["url"],
            tags=tuple(item.get("tags", [])),
        )
        for item in payload
    ]


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "source"


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = []
    skip_prefixes = (
        "Retrieved from",
        "This page was last edited",
        "Privacy policy",
        "About FreeCAD Documentation",
        "Disclaimers",
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
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

    headers = {
        "User-Agent": "FreeCADPromptForge/0.1 (+local personal knowledge base)",
        "Accept": "text/html, text/plain, application/xhtml+xml",
    }
    response = requests.get(source.url, headers=headers, timeout=timeout)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type or response.text.lstrip().startswith("<"):
        return html_to_text(response.text, source.url)
    return _normalize_text(response.text)


def write_raw_source(
    source: KnowledgeSource,
    text: str,
    output_dir: Path = RAW_KNOWLEDGE_DIR,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
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
    path = output_dir / f"{slugify(source.title)}.md"
    path.write_text(body, encoding="utf-8")
    return path


def _read_raw_metadata(path: Path) -> dict[str, str]:
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
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
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

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            flush()
            for start in range(0, len(paragraph), max_chars - overlap_chars):
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


def build_index_from_raw(
    raw_dir: Path = RAW_KNOWLEDGE_DIR,
    index_path: Path = CHUNKS_FILE,
) -> list[dict[str, object]]:
    raw_files = sorted(raw_dir.glob("*.md"))
    chunks: list[dict[str, object]] = []
    for raw_file in raw_files:
        metadata = _read_raw_metadata(raw_file)
        for idx, chunk in enumerate(chunk_text(metadata["text"])):
            chunks.append(
                {
                    "id": f"{raw_file.stem}:{idx}",
                    "title": metadata["title"],
                    "url": metadata["url"],
                    "tags": metadata["tags"],
                    "source_file": str(raw_file),
                    "chunk_index": idx,
                    "text": chunk,
                }
            )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return chunks


def ingest_sources(sources: Iterable[KnowledgeSource] | None = None) -> list[Path]:
    sources = list(sources or load_sources())
    written: list[Path] = []
    for source in sources:
        text = fetch_source(source)
        written.append(write_raw_source(source, text))
    build_index_from_raw()
    return written
