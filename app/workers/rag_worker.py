from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.rag_ingest_v2 import ingest_v2


@dataclass(frozen=True)
class RagWorkerResult:
    ok: bool
    chunks: int = 0
    documents: int = 0
    source_files: int = 0
    audit: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class RagWorker:
    def __init__(self) -> None:
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def rebuild(self, on_status: Callable[[str], None] | None = None) -> RagWorkerResult:
        if on_status:
            on_status("Iniciando RAG v2 incremental/cacheado")
        if self.cancel_requested:
            return RagWorkerResult(False, message="RAG cancelado antes de iniciar.")
        audit = ingest_v2()
        if on_status:
            on_status(f"RAG pronto: {audit.get('chunks', 0)} chunks")
        return RagWorkerResult(
            ok=bool(audit.get("chunks", 0)),
            chunks=int(audit.get("chunks", 0)),
            documents=int(audit.get("documents", 0)),
            source_files=int(audit.get("source_files", 0)),
            audit=audit,
            message="RAG reconstruido.",
        )
