from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / "data"
DOCS_DIR = DATA_DIR / "docs"
RAG_DIR = DATA_DIR / "rag"
MACROS_DIR = DATA_DIR / "macros"
OUTPUT_DIR = DATA_DIR / "outputs"
JOBS_DIR = OUTPUT_DIR / "jobs"
LOG_DIR = DATA_DIR / "logs"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
REPAIRS_DIR = DATA_DIR / "repairs"
VIEWER_CACHE_DIR = DATA_DIR / "cache" / "viewer_lod"
SOURCES_FILE = RAG_DIR / "sources.json"
CHUNKS_FILE = RAG_DIR / "chunks.json"
VECTORS_FILE = RAG_DIR / "tfidf.joblib"

# Backward-compatible names for older helper scripts/imports.
KNOWLEDGE_DIR = RAG_DIR
RAW_KNOWLEDGE_DIR = DOCS_DIR
INDEX_DIR = RAG_DIR

DEFAULT_FREECAD_CANDIDATES = [
    "freecadcmd",
    "FreeCADCmd",
    "freecad",
    "FreeCAD",
    str(Path.home() / "bin" / "freecad"),
    str(Path.home() / "Applications" / "FreeCAD_1.1.1-Linux-x86_64-py311.AppImage"),
    *[str(path) for path in sorted((Path.home() / "Applications").glob("FreeCAD*.AppImage"))],
    *[str(path) for path in sorted(APP_DIR.glob("FreeCAD*.AppImage"))],
    *[str(path) for path in sorted(Path("/opt").glob("**/FreeCAD*.AppImage"))[:20]],
]

for directory in (DATA_DIR, DOCS_DIR, RAG_DIR, MACROS_DIR, OUTPUT_DIR, JOBS_DIR, LOG_DIR, DIAGNOSTICS_DIR, REPAIRS_DIR, VIEWER_CACHE_DIR):
    directory.mkdir(parents=True, exist_ok=True)
