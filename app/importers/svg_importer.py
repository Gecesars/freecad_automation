from __future__ import annotations

import argparse
from pathlib import Path

from app.freecad_runner import run_macro
from app.importers.base_importer import BaseImporter, bbox_from_points
from app.importers.import_report import ImportReport
from app.settings import DIAGNOSTICS_DIR, MACROS_DIR, OUTPUT_DIR
from app.utils import slugify


class SvgImporter(BaseImporter):
    name = "svg"

    def import_file(self, path: Path, scale: float = 1.0, extrude: bool = True, thickness: float = 2.0, center: bool = True) -> ImportReport:
        try:
            from svgpathtools import svg2paths
        except Exception as exc:
            return ImportReport(False, self.name, str(path), f"svgpathtools indisponivel: {exc}", diagnostics=["pip install svgpathtools"])
        paths, attributes = svg2paths(str(path))
        points: list[tuple[float, float]] = []
        for svg_path in paths:
            xmin, xmax, ymin, ymax = svg_path.bbox()
            points.extend([(xmin * scale, ymin * scale), (xmax * scale, ymax * scale)])
        bbox = bbox_from_points(points)
        outputs: dict[str, str] = {}
        diagnostics: list[str] = []
        if extrude and bbox["x_length"] > 0 and bbox["y_length"] > 0:
            macro = self._write_extrusion_macro(path, bbox, thickness, center)
            result = run_macro(macro, output_dir=self.output_dir)
            outputs = {key: str(value) for key, value in result.output_paths.items()}
            diagnostics.append(result.message)
            if not result.ok:
                diagnostics.append(result.stdout[-2000:])
        report = ImportReport(
            ok=bool(points),
            importer=self.name,
            source_path=str(path),
            message="SVG importado por svgpathtools; paths analisados e extrusao gerada." if points else "SVG lido, mas nenhum path suportado foi encontrado.",
            entity_count=len(paths),
            bbox=bbox,
            output_paths=outputs,
            diagnostics=diagnostics,
        )
        report.save(self.report_path(path))
        return report

    def _write_extrusion_macro(self, source_path: Path, bbox: dict[str, float], thickness: float, center: bool) -> Path:
        base = slugify(source_path.stem + "-svg-import")
        macro = MACROS_DIR / f"{base}.py"
        x = -bbox["x_length"] / 2 if center else bbox["xmin"]
        y = -bbox["y_length"] / 2 if center else bbox["ymin"]
        macro.write_text(
            "\n".join(
                [
                    "import os",
                    "import FreeCAD as App",
                    "import Part",
                    "from FreeCAD import Vector",
                    f"BASE_NAME = {base!r}",
                    f"DEFAULT_OUTPUT_DIR = {str(self.output_dir)!r}",
                    "doc = App.newDocument('SvgImport')",
                    f"shape = Part.makeBox({bbox['x_length']}, {bbox['y_length']}, {thickness}, Vector({x}, {y}, 0))",
                    "obj = doc.addObject('Part::Feature', 'ImportedSvgEnvelope')",
                    "obj.Shape = shape",
                    "doc.recompute()",
                    "output_dir = os.environ.get('PROMPT_FORGE_OUTPUT', DEFAULT_OUTPUT_DIR)",
                    "os.makedirs(output_dir, exist_ok=True)",
                    "doc.saveAs(os.path.join(output_dir, BASE_NAME + '.FCStd'))",
                    "Part.export([obj], os.path.join(output_dir, BASE_NAME + '.step'))",
                    "import Mesh",
                    "Mesh.export([obj], os.path.join(output_dir, BASE_NAME + '.stl'))",
                    "shape.exportBrep(os.path.join(output_dir, BASE_NAME + '.brep'))",
                    "Mesh.export([obj], os.path.join(output_dir, BASE_NAME + '.obj'))",
                    "open(os.path.join(output_dir, BASE_NAME + '_metadata.json'), 'w', encoding='utf-8').write('{}')",
                    "open(os.path.join(output_dir, BASE_NAME + '_build_report.md'), 'w', encoding='utf-8').write('# SVG Import Build Report\\n')",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return macro


def _make_sample(path: Path) -> Path:
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="30" viewBox="0 0 50 30">'
        '<path d="M 0 0 L 50 0 L 50 30 L 0 30 Z"/></svg>',
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa SVG e gera relatorio.")
    parser.add_argument("path", nargs="?", help="Arquivo SVG")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.path) if args.path else DIAGNOSTICS_DIR / "sample_import.svg"
    if args.self_test:
        path.parent.mkdir(parents=True, exist_ok=True)
        _make_sample(path)
    report = SvgImporter(OUTPUT_DIR).import_file(path)
    print(report.to_markdown())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
