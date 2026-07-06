from __future__ import annotations

import argparse
from pathlib import Path

from app.freecad_runner import run_macro
from app.importers.base_importer import BaseImporter
from app.importers.import_report import ImportReport
from app.settings import MACROS_DIR, OUTPUT_DIR
from app.utils import slugify


class StepImporter(BaseImporter):
    name = "step"

    def import_file(self, path: Path) -> ImportReport:
        if not path.exists():
            return ImportReport(False, self.name, str(path), "Arquivo STEP/BREP nao encontrado.")
        macro = self._write_macro(path)
        result = run_macro(macro, output_dir=self.output_dir)
        report = ImportReport(
            ok=result.ok,
            importer=self.name,
            source_path=str(path),
            message=result.message,
            output_paths={key: str(value) for key, value in result.output_paths.items()},
            diagnostics=[result.stdout[-3000:], result.stderr[-3000:]],
        )
        report.save(self.report_path(path))
        return report

    def _write_macro(self, source_path: Path) -> Path:
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        base = slugify(source_path.stem + "-step-import")
        macro = MACROS_DIR / f"{base}.py"
        suffix = source_path.suffix.lower()
        macro.write_text(
            "\n".join(
                [
                    "import json",
                    "import os",
                    "import FreeCAD as App",
                    "import Part",
                    f"SOURCE_PATH = {str(source_path)!r}",
                    f"SOURCE_SUFFIX = {suffix!r}",
                    f"BASE_NAME = {base!r}",
                    f"DEFAULT_OUTPUT_DIR = {str(self.output_dir)!r}",
                    "doc = App.newDocument('ImportedStepBrep')",
                    "if SOURCE_SUFFIX in ('.brep', '.brp'):",
                    "    shape = Part.Shape()",
                    "    shape.read(SOURCE_PATH)",
                    "    obj = doc.addObject('Part::Feature', 'ImportedBrep')",
                    "    obj.Shape = shape",
                    "else:",
                    "    import Import",
                    "    Import.insert(SOURCE_PATH, doc.Name)",
                    "objects = [obj for obj in doc.Objects if hasattr(obj, 'Shape') and not obj.Shape.isNull()]",
                    "if not objects:",
                    "    raise RuntimeError('Nenhum objeto Shape importado')",
                    "doc.recompute()",
                    "output_dir = os.environ.get('PROMPT_FORGE_OUTPUT', DEFAULT_OUTPUT_DIR)",
                    "os.makedirs(output_dir, exist_ok=True)",
                    "fcstd = os.path.join(output_dir, BASE_NAME + '.FCStd')",
                    "step = os.path.join(output_dir, BASE_NAME + '.step')",
                    "stl = os.path.join(output_dir, BASE_NAME + '.stl')",
                    "obj_path = os.path.join(output_dir, BASE_NAME + '.obj')",
                    "brep = os.path.join(output_dir, BASE_NAME + '.brep')",
                    "metadata = os.path.join(output_dir, BASE_NAME + '_metadata.json')",
                    "report = os.path.join(output_dir, BASE_NAME + '_build_report.md')",
                    "doc.saveAs(fcstd)",
                    "Part.export(objects, step)",
                    "import Mesh",
                    "Mesh.export(objects, stl)",
                    "Mesh.export(objects, obj_path)",
                    "objects[0].Shape.exportBrep(brep)",
                    "bbox = objects[0].Shape.BoundBox",
                    "payload = {'base_name': BASE_NAME, 'source': SOURCE_PATH, 'objects': len(objects), 'validation': {'valid': bool(objects[0].Shape.isValid()), 'bbox': {'x_length': bbox.XLength, 'y_length': bbox.YLength, 'z_length': bbox.ZLength}}}",
                    "open(metadata, 'w', encoding='utf-8').write(json.dumps(payload, ensure_ascii=False, indent=2))",
                    "open(report, 'w', encoding='utf-8').write('# STEP/BREP Import Build Report\\n\\n' + json.dumps(payload, ensure_ascii=False, indent=2))",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return macro


def import_step(path: Path) -> ImportReport:
    return StepImporter(OUTPUT_DIR).import_file(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa STEP/STP/BREP via FreeCAD.")
    parser.add_argument("path")
    args = parser.parse_args(argv)
    report = import_step(Path(args.path))
    print(report.to_markdown())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
