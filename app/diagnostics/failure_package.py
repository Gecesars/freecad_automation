from __future__ import annotations

import json
import platform
import shutil
import zipfile
from pathlib import Path
from typing import Any

from app.geometry_validator import validate_geometry
from app.models import Feature, GeneratedDesign, PartSpec
from app.settings import DIAGNOSTICS_DIR, LOG_DIR


def create_failure_package(
    design: GeneratedDesign | None = None,
    job_dir: Path | None = None,
    freecad_payload: dict[str, Any] | None = None,
    rag_payload: list[dict[str, Any]] | None = None,
) -> Path:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = DIAGNOSTICS_DIR / "last_failure_package"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    if design:
        if design.macro_path.exists():
            shutil.copy2(design.macro_path, work_dir / "macro.py")
        (work_dir / "parsed_prompt.json").write_text(json.dumps(design.spec.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        (work_dir / "geometry_validation.json").write_text(
            json.dumps(validate_geometry(design.spec), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rag_payload = rag_payload or [
            {
                "title": item.title,
                "url": item.url,
                "score": item.score,
                "source_file": item.source_file,
                "chunk_index": item.chunk_index,
            }
            for item in design.rag_results
        ]

    (work_dir / "rag_results.json").write_text(json.dumps(rag_payload or [], ensure_ascii=False, indent=2), encoding="utf-8")
    if freecad_payload is not None:
        (work_dir / "runner_report.json").write_text(json.dumps(freecad_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if job_dir and job_dir.exists():
        if not design:
            macro_files = sorted(job_dir.glob("*.py"), key=lambda path: path.stat().st_mtime, reverse=True)
            if macro_files:
                shutil.copy2(macro_files[0], work_dir / "macro.py")
            metadata_path = job_dir / "metadata.json"
            if metadata_path.exists():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    spec_payload = metadata.get("part_spec", {})
                    (work_dir / "parsed_prompt.json").write_text(
                        json.dumps(spec_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    spec = PartSpec(
                        prompt="",
                        part_type=str(spec_payload.get("part_type", "")),
                        dimensions=dict(spec_payload.get("dimensions", {})),
                        features=tuple(
                            Feature(str(item.get("kind", "")), dict(item.get("params", {})))
                            for item in spec_payload.get("features", [])
                        ),
                        material=spec_payload.get("material"),
                        assumptions=tuple(spec_payload.get("assumptions", [])),
                        warnings=tuple(spec_payload.get("warnings", [])),
                    )
                    (work_dir / "geometry_validation.json").write_text(
                        json.dumps(validate_geometry(spec), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as exc:
                    (work_dir / "geometry_validation.json").write_text(
                        json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
        for source_name, target_name in (
            ("runtime_report.json", "runner_report.json"),
            ("job_result.json", "job_result.json"),
            ("metadata.json", "metadata.json"),
            ("build_report.md", "build_report.md"),
        ):
            source = job_dir / source_name
            if source.exists():
                shutil.copy2(source, work_dir / target_name)

    last_logs = sorted(LOG_DIR.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)[:5]
    for log_path in last_logs:
        target = "freecad_minimal_test.log" if "minimal_test" in log_path.name else log_path.name
        shutil.copy2(log_path, work_dir / target)

    env_text = "\n".join(
        [
            f"platform={platform.platform()}",
            f"python={platform.python_version()}",
            f"job_dir={job_dir or ''}",
            f"macro={design.macro_path if design else ''}",
        ]
    )
    (work_dir / "environment.txt").write_text(env_text, encoding="utf-8")
    (work_dir / "stdout.log").write_text(str((freecad_payload or {}).get("stdout", "")), encoding="utf-8")
    (work_dir / "stderr.log").write_text(str((freecad_payload or {}).get("stderr", "")), encoding="utf-8")

    zip_path = DIAGNOSTICS_DIR / "last_failure.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(work_dir.iterdir()):
            archive.write(path, path.name)
    return zip_path
