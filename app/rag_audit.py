from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.rag_index_v2 import V2_AUDIT_FILE
from app.rag_retriever_v2 import HybridRagRetriever
from app.settings import RAG_DIR


def audit_query(query: str, limit: int = 8) -> dict[str, object]:
    retriever = HybridRagRetriever()
    results = retriever.search(query, limit=limit)
    return {
        "query": query,
        "count": len(results),
        "results": [
            {
                "title": result.title,
                "score": result.score,
                "url": result.url,
                "source_file": result.source_file,
                "chunk_index": result.chunk_index,
                "excerpt": result.text[:500],
            }
            for result in results
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audita consultas no RAG v2.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args(argv)
    payload = audit_query(args.query, args.limit)
    report_path = RAG_DIR / "last_rag_query.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if V2_AUDIT_FILE.exists():
        payload["corpus"] = json.loads(V2_AUDIT_FILE.read_text(encoding="utf-8"))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["count"] >= min(args.limit, 5) else 1


if __name__ == "__main__":
    raise SystemExit(main())
