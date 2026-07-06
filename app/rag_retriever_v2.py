from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from app.models import SearchResult
from app.rag_index_v2 import V2_CHUNKS_FILE, V2_INDEX_FILE, tokenize
from app.rag_store import IGNORED_FILENAMES, TECHNICAL_TERMS


DOMAIN_TERMS = {
    "headless": ("freecadcmd", "console", "headless", "xvfb", "macro"),
    "import": ("import", "dxf", "svg", "dwg", "draft", "open"),
    "export": ("export", "step", "stl", "obj", "brep", "mesh"),
    "viewer": ("freecadgui", "viewer", "pyside", "qt", "view"),
    "part": ("part", "makebox", "makecylinder", "cut", "fuse", "shape"),
    "sketcher": ("sketcher", "constraint", "sketch"),
}


class HybridRagRetriever:
    def __init__(self, chunks_path: Path = V2_CHUNKS_FILE, index_path: Path = V2_INDEX_FILE) -> None:
        self.chunks_path = chunks_path
        self.index_path = index_path
        self.chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else []
        self.index = joblib.load(index_path) if index_path.exists() else None

    def search(self, query: str, limit: int = 8, domain: str | None = None, technical: bool = False) -> list[SearchResult]:
        if not self.chunks or not self.index:
            return []
        tokens = tokenize(query)
        bm25_scores = np.array(self.index["bm25"].get_scores(tokens), dtype=float)
        query_vec = self.index["vectorizer"].transform([query])
        tfidf_scores = cosine_similarity(query_vec, self.index["matrix"]).ravel()
        if bm25_scores.max() > 0:
            bm25_scores = bm25_scores / bm25_scores.max()
        if tfidf_scores.max() > 0:
            tfidf_scores = tfidf_scores / tfidf_scores.max()
        scores = 0.55 * bm25_scores + 0.45 * tfidf_scores
        query_lower = query.lower()
        selected_domain = domain or self._infer_domain(query_lower)
        if selected_domain:
            terms = DOMAIN_TERMS.get(selected_domain, ())
            for idx, chunk in enumerate(self.chunks):
                text = (str(chunk.get("text", "")) + " " + str(chunk.get("tags", ""))).lower()
                if any(term in text for term in terms):
                    scores[idx] += 0.08
        ranked = np.argsort(scores)[::-1][: max(limit * 4, limit)]
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

    def _infer_domain(self, query: str) -> str | None:
        for domain, terms in DOMAIN_TERMS.items():
            if any(term in query for term in terms):
                return domain
        return None

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
