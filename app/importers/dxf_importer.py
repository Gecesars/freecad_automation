from __future__ import annotations

import argparse
from pathlib import Path

from app.freecad_runner import run_macro
from app.importers.base_importer import BaseImporter, bbox_from_points
from app.importers.import_report import ImportReport
from app.settings import DIAGNOSTICS_DIR, MACROS_DIR, OUTPUT_DIR
from app.utils import slugify


class DxfImporter(BaseImporter):
    name = "dxf"

    def import_file(
        self,
        path: Path,
        unit: str = "mm",
        scale: float = 1.0,
        extrude: bool = True,
        thickness: float = 2.0,
        center: bool = True,
        selected_layers: list[str] | None = None,
    ) -> ImportReport:
        try:
            import ezdxf
        except Exception as exc:
            return ImportReport(False, self.name, str(path), f"ezdxf indisponivel: {exc}", diagnostics=["pip install ezdxf"])

        doc = ezdxf.readfile(str(path))
        modelspace = doc.modelspace()
        layers = sorted({entity.dxf.layer for entity in modelspace if hasattr(entity.dxf, "layer")})
        selected = set(selected_layers or layers)
        points: list[tuple[float, float]] = []
        entity_count = 0
        for entity in modelspace:
            layer = getattr(entity.dxf, "layer", "0")
            if layer not in selected:
                continue
            entity_count += 1
            etype = entity.dxftype()
            if etype == "LINE":
                points.append((float(entity.dxf.start.x) * scale, float(entity.dxf.start.y) * scale))
                points.append((float(entity.dxf.end.x) * scale, float(entity.dxf.end.y) * scale))
            elif etype in {"LWPOLYLINE", "POLYLINE"}:
                try:
                    for point in entity.get_points():
                        points.append((float(point[0]) * scale, float(point[1]) * scale))
                except Exception:
                    pass
            elif etype == "CIRCLE":
                cx, cy, r = float(entity.dxf.center.x) * scale, float(entity.dxf.center.y) * scale, float(entity.dxf.radius) * scale
                points.extend([(cx - r, cy - r), (cx + r, cy + r)])
            elif etype == "ARC":
                cx, cy, r = float(entity.dxf.center.x) * scale, float(entity.dxf.center.y) * scale, float(entity.dxf.radius) * scale
                points.extend([(cx - r, cy - r), (cx + r, cy + r)])

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
            message="DXF importado por ezdxf; geometria 2D analisada e extrusao gerada." if points else "DXF lido, mas nenhuma entidade suportada foi encontrada.",
            layers=layers,
            entity_count=entity_count,
            bbox=bbox,
            output_paths=outputs,
            diagnostics=diagnostics,
        )
        report.save(self.report_path(path))
        return report

    def _write_extrusion_macro(self, source_path: Path, bbox: dict[str, float], thickness: float, center: bool) -> Path:
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        base = slugify(source_path.stem + "-dxf-import")
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
                    "doc = App.newDocument('DxfImport')",
                    f"shape = Part.makeBox({bbox['x_length']}, {bbox['y_length']}, {thickness}, Vector({x}, {y}, 0))",
                    "obj = doc.addObject('Part::Feature', 'ImportedDxfEnvelope')",
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
                    "open(os.path.join(output_dir, BASE_NAME + '_build_report.md'), 'w', encoding='utf-8').write('# DXF Import Build Report\\n')",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return macro


def _make_sample(path: Path) -> Path:
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (40, 0), (40, 20), (0, 20), (0, 0)], close=True, dxfattribs={"layer": "OUTLINE"})
    msp.add_circle((20, 10), 3, dxfattribs={"layer": "HOLES"})
    doc.saveas(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa DXF e gera relatorio.")
    parser.add_argument("path", nargs="?", help="Arquivo DXF")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.path) if args.path else DIAGNOSTICS_DIR / "sample_import.dxf"
    if args.self_test:
        path.parent.mkdir(parents=True, exist_ok=True)
        _make_sample(path)
    report = DxfImporter(OUTPUT_DIR).import_file(path)
    print(report.to_markdown())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
