from __future__ import annotations

import json
import py_compile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.agent import PromptAgent
from app.models import GeneratedDesign
from app.rag_store import LocalRagStore
from app.settings import JOBS_DIR
from app.utils import slugify
from app.workers.freecad_worker import FreeCADJob, FreeCADWorker, FreeCADWorkerResult


StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class CadJobResult:
    job_id: str
    prompt: str
    job_dir: Path
    design: GeneratedDesign
    freecad: FreeCADWorkerResult | None
    status: str
    elapsed_sec: float

    @property
    def ok(self) -> bool:
        return self.freecad is not None and self.freecad.success

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "prompt": self.prompt,
            "job_dir": str(self.job_dir),
            "macro_path": str(self.design.macro_path),
            "expected_outputs": {key: str(value) for key, value in self.design.output_paths.items()},
            "freecad": self.freecad.to_json_dict() if self.freecad else None,
            "status": self.status,
            "elapsed_sec": self.elapsed_sec,
            "deepseek": {
                "used": self.design.llm_used,
                "model": self.design.llm_model,
                "notes": self.design.llm_notes,
            },
        }


class JobManager:
    def __init__(
        self,
        rag: LocalRagStore | None = None,
        jobs_dir: Path = JOBS_DIR,
        auto_correct_geometry: bool = True,
    ) -> None:
        self.rag = rag or LocalRagStore()
        self.jobs_dir = jobs_dir
        self.auto_correct_geometry = auto_correct_geometry
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def create_job_dir(self, prompt: str) -> tuple[str, Path]:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_id = f"{stamp}_{slugify(prompt[:48])}"
        job_id = base_id
        job_dir = self.jobs_dir / job_id
        counter = 2
        while job_dir.exists():
            job_id = f"{base_id}_{counter}"
            job_dir = self.jobs_dir / job_id
            counter += 1
        job_dir.mkdir(parents=True, exist_ok=False)
        return job_id, job_dir

    def generate(self, prompt: str, on_status: StatusCallback | None = None) -> tuple[str, Path, GeneratedDesign]:
        started = datetime.now()
        job_id, job_dir = self.create_job_dir(prompt)
        self._status(on_status, f"Job {job_id}: interpretando prompt")
        agent = PromptAgent(
            self.rag,
            macros_dir=job_dir,
            output_dir=job_dir,
            auto_correct_geometry=self.auto_correct_geometry,
        )
        self._status(on_status, "Parser local e validador geometrico ativos")
        self._status(on_status, "Consultando RAG tecnico e gerando macro")
        design = agent.generate(prompt)
        self._status(on_status, "Validando sintaxe da macro")
        py_compile.compile(str(design.macro_path), doraise=True)
        (job_dir / "job_request.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "prompt": prompt,
                    "created_at": started.isoformat(timespec="seconds"),
                    "macro_path": str(design.macro_path),
                    "deepseek_used": design.llm_used,
                    "deepseek_model": design.llm_model,
                    "deepseek_notes": design.llm_notes,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return job_id, job_dir, design

    def run_prompt(
        self,
        prompt: str,
        run_freecad: bool = True,
        timeout_sec: int = 120,
        on_status: StatusCallback | None = None,
        on_line=None,
    ) -> CadJobResult:
        started = datetime.now()
        job_id, job_dir, design = self.generate(prompt, on_status=on_status)
        freecad_result: FreeCADWorkerResult | None = None
        if run_freecad:
            effective_timeout = self._timeout_for_design(design, timeout_sec)
            self._status(on_status, f"Iniciando FreeCAD headless com timeout real de {effective_timeout}s")
            job = FreeCADJob(
                prompt=prompt,
                macro_path=design.macro_path,
                output_dir=job_dir,
                timeout_sec=effective_timeout,
                job_id=job_id,
            )
            freecad_result = FreeCADWorker().run(job, on_line=on_line)
            if freecad_result.success:
                self._status(on_status, "FreeCAD concluiu; arquivos CAD confirmados")
            else:
                self._status(on_status, f"FreeCAD falhou: {freecad_result.message}")
        elapsed = (datetime.now() - started).total_seconds()
        result = CadJobResult(
            job_id=job_id,
            prompt=prompt,
            job_dir=job_dir,
            design=design,
            freecad=freecad_result,
            status="completed" if (freecad_result.success if freecad_result else True) else "error",
            elapsed_sec=elapsed,
        )
        (job_dir / "job_result.json").write_text(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _status(self, callback: StatusCallback | None, message: str) -> None:
        if callback:
            callback(message)

    def _timeout_for_design(self, design: GeneratedDesign, requested_timeout: int) -> int:
        if design.spec.part_type == "flange":
            return min(requested_timeout, 30)
        if design.spec.part_type in {"plate", "cylinder"}:
            return min(requested_timeout, 90)
        return min(max(requested_timeout, 30), 180)
