from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import joblib
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer

from app.settings import CHUNKS_FILE, RAG_DIR, VECTORS_FILE

V2_CHUNKS_FILE = RAG_DIR / "chunks_v2.json"
V2_INDEX_FILE = RAG_DIR / "hybrid_index_v2.joblib"
V2_AUDIT_FILE = RAG_DIR / "rag_v2_audit.json"


def tokenize(text: str) -> list[str]:
    return re.findall(r"(?u)\b[\w./+-]{2,}\b", text.lower())


def build_hybrid_index(chunks_path: Path = V2_CHUNKS_FILE, index_path: Path = V2_INDEX_FILE) -> dict[str, object]:
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    texts = [str(chunk.get("text", "")) for chunk in chunks]
    tokenized = [tokenize(text) for text in texts]
    bm25 = BM25Okapi(tokenized)
    vectorizer = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        ngram_range=(1, 2),
        min_df=1,
        token_pattern=r"(?u)\b[\w./+-]{2,}\b",
    )
    matrix = vectorizer.fit_transform(texts)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"bm25": bm25, "vectorizer": vectorizer, "matrix": matrix, "chunks_path": str(chunks_path)}, index_path)
    # Keep the legacy path in sync so existing UI/retriever code sees the larger corpus.
    CHUNKS_FILE.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    joblib.dump({"vectorizer": vectorizer, "matrix": matrix}, VECTORS_FILE)
    terms = Counter(token for row in tokenized for token in row)
    audit = {
        "chunks": len(chunks),
        "documents": len({chunk.get("source_file") for chunk in chunks}),
        "top_terms": terms.most_common(80),
        "index_path": str(index_path),
        "chunks_path": str(chunks_path),
    }
    V2_AUDIT_FILE.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main() -> int:
    audit = build_hybrid_index()
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
