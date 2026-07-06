from __future__ import annotations

import json

from app.rag_store import LocalRagStore


def test_rag_store_returns_chunks(tmp_path) -> None:
    chunks_path = tmp_path / "chunks.json"
    vectors_path = tmp_path / "tfidf.joblib"
    chunks = [
        {
            "title": "Part scripting",
            "url": "https://wiki.freecad.org/Part_scripting",
            "text": "Use Part.makeBox and Part.makeCylinder with cut and fuse for boolean operations.",
            "source_file": "part.md",
            "chunk_index": 0,
        },
        {
            "title": "Mesh export",
            "url": "https://wiki.freecad.org/Mesh_Scripting",
            "text": "Mesh export writes STL files from FreeCAD objects.",
            "source_file": "mesh.md",
            "chunk_index": 0,
        },
    ]
    chunks_path.write_text(json.dumps(chunks), encoding="utf-8")
    store = LocalRagStore(chunks_path=chunks_path, vectors_path=vectors_path)
    results = store.search("make cylinder boolean cut", limit=1)
    assert results
    assert results[0].title == "Part scripting"
    assert vectors_path.exists()
