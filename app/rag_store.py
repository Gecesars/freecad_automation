from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.models import SearchResult
from app.settings import CHUNKS_FILE, VECTORS_FILE


TECHNICAL_TERMS = (
    "freecad",
    "part",
    "makecylinder",
    "makebox",
    "cut",
    "fuse",
    "shape",
    "isvalid",
    "boundbox",
    "part.export",
    "mesh.export",
    "doc.saveas",
    "app.newdocument",
    "recompute",
)

IGNORED_FILENAMES = {"licencia", "licencia.md", "license", "license.md", "licence", "licence.md", "copying", "copying.md"}


class LocalRagStore:
    def __init__(
        self,
        chunks_path: Path = CHUNKS_FILE,
        vectors_path: Path = VECTORS_FILE,
    ) -> None:
        self.chunks_path = chunks_path
        self.vectors_path = vectors_path
        self.chunks: list[dict[str, object]] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None
        self.reload()

    @property
    def ready(self) -> bool:
        return bool(self.chunks) and self.vectorizer is not None and self.matrix is not None

    def reload(self) -> None:
        if not self.chunks_path.exists():
            self.chunks = []
            self.vectorizer = None
            self.matrix = None
            return
        self.chunks = json.loads(self.chunks_path.read_text(encoding="utf-8"))
        if self.vectors_path.exists():
            try:
                payload = joblib.load(self.vectors_path)
                self.vectorizer = payload["vectorizer"]
                self.matrix = payload["matrix"]
                if getattr(self.matrix, "shape", (0, 0))[0] == len(self.chunks):
                    return
            except Exception:
                pass
        self.rebuild_vectors()

    def rebuild_vectors(self) -> None:
        texts = [str(chunk.get("text", "")) for chunk in self.chunks]
        if not texts:
            self.vectorizer = None
            self.matrix = None
            return
        self.vectorizer = TfidfVectorizer(
            lowercase=True,
            strip_accents="unicode",
            ngram_range=(1, 2),
            min_df=1,
            token_pattern=r"(?u)\b[\w./+-]{2,}\b",
        )
        self.matrix = self.vectorizer.fit_transform(texts)
        self.vectors_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"vectorizer": self.vectorizer, "matrix": self.matrix}, self.vectors_path)

    def search(self, query: str, limit: int = 5, technical: bool = False) -> list[SearchResult]:
        query = query.strip()
        if not query or not self.ready or self.vectorizer is None or self.matrix is None:
            return []
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.matrix).ravel()
        ranked = np.argsort(scores)[::-1][: max(limit * 8, limit)]
        results: list[SearchResult] = []
        for idx in ranked:
            score = float(scores[int(idx)])
            if score <= 0:
                continue
            chunk = self.chunks[int(idx)]
            if self._is_irrelevant(chunk, technical):
                continue
            if technical and score < 0.35:
                continue
            results.append(
                SearchResult(
                    title=str(chunk.get("title", "")),
                    url=str(chunk.get("url", "")),
                    text=str(chunk.get("text", "")),
                    score=score,
                    source_file=str(chunk.get("source_file", "")),
                    chunk_index=int(chunk.get("chunk_index", 0)),
                )
            )
            if len(results) >= limit:
                break
        return results

    def format_results(self, results: list[SearchResult]) -> str:
        if not results:
            return "RAG sem contexto relevante."
        lines: list[str] = []
        for index, result in enumerate(results, start=1):
            excerpt = result.text.strip().replace("\n", " ")
            if len(excerpt) > 900:
                excerpt = excerpt[:900].rstrip() + "..."
            lines.append(
                f"[{index}] {result.title} | score={result.score:.3f}\n"
                f"{result.url}\n"
                f"{excerpt}"
            )
        return "\n\n".join(lines)

    def _is_irrelevant(self, chunk: dict[str, object], technical: bool) -> bool:
        source = Path(str(chunk.get("source_file", ""))).name.lower()
        title = str(chunk.get("title", "")).lower()
        text = str(chunk.get("text", "")).lower()
        if source in IGNORED_FILENAMES or title.strip() in IGNORED_FILENAMES:
            return True
        has_technical = any(term in text for term in TECHNICAL_TERMS)
        if "readme" in source and not has_technical:
            return True
        return bool(technical and not has_technical)
