from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from app.importers.dxf_importer import DxfImporter
from app.importers.import_report import ImportReport
from app.settings import OUTPUT_DIR


CONVERTERS = ["dwg2dxf", "ODAFileConverter", "TeighaFileConverter", "qcad", "libredwg"]


def detect_converters() -> dict[str, str | None]:
    return {name: shutil.which(name) for name in CONVERTERS}


class DwgImporter:
    name = "dwg"

    def __init__(self, output_dir: Path = OUTPUT_DIR) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def doctor(self) -> ImportReport:
        converters = detect_converters()
        found = {name: path for name, path in converters.items() if path}
        if found:
            message = "Conversor DWG detectado: " + ", ".join(f"{name}={path}" for name, path in found.items())
            ok = True
        else:
            message = (
                "DWG e formato proprietario. Este ambiente nao possui conversor DWG instalado. "
                "Instale LibreDWG, ODA/Teigha File Converter ou QCAD Pro, ou converta manualmente para DXF."
            )
            ok = False
        return ImportReport(
            ok=ok,
            importer=self.name,
            source_path="",
            message=message,
            diagnostics=[f"{name}: {path or 'nao encontrado'}" for name, path in converters.items()],
        )

    def import_file(self, path: Path) -> ImportReport:
        converters = detect_converters()
        dwg2dxf = converters.get("dwg2dxf")
        if not dwg2dxf:
            report = self.doctor()
            report.save(self.output_dir / f"{path.stem}_dwg_import_report.md")
            return report
        dxf_path = self.output_dir / f"{path.stem}.converted.dxf"
        proc = subprocess.run([dwg2dxf, str(path), str(dxf_path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=False)
        if proc.returncode != 0 or not dxf_path.exists():
            return ImportReport(False, self.name, str(path), "Conversao DWG para DXF falhou.", diagnostics=[proc.stdout, proc.stderr])
        return DxfImporter(self.output_dir).import_file(dxf_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostica/importa DWG.")
    parser.add_argument("path", nargs="?")
    parser.add_argument("--doctor", action="store_true")
    args = parser.parse_args(argv)
    importer = DwgImporter(OUTPUT_DIR)
    report = importer.doctor() if args.doctor or not args.path else importer.import_file(Path(args.path))
    print(report.to_markdown())
    return 0 if report.ok or args.doctor else 1


if __name__ == "__main__":
    raise SystemExit(main())
