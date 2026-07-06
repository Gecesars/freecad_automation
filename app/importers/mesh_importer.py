from __future__ import annotations

import argparse
from pathlib import Path

from app.importers.base_importer import BaseImporter
from app.importers.import_report import ImportReport
from app.settings import OUTPUT_DIR
from app.utils import slugify


class MeshImporter(BaseImporter):
    name = "mesh"

    def import_file(self, path: Path) -> ImportReport:
        if not path.exists():
            return ImportReport(False, self.name, str(path), "Arquivo de malha nao encontrado.")
        try:
            import numpy as np
            import trimesh
        except Exception as exc:
            return ImportReport(False, self.name, str(path), f"trimesh/numpy indisponivel: {exc}")
        mesh = trimesh.load_mesh(str(path), force="mesh")
        if mesh.is_empty:
            return ImportReport(False, self.name, str(path), "Malha vazia.")
        bounds = np.asarray(mesh.bounds, dtype=float)
        lengths = bounds[1] - bounds[0]
        base = slugify(path.stem + "-mesh-import")
        normalized = self.output_dir / f"{base}{path.suffix.lower()}"
        mesh.export(str(normalized))
        report = ImportReport(
            ok=True,
            importer=self.name,
            source_path=str(path),
            message="Malha carregada para viewer fallback e salva em copia normalizada.",
            entity_count=int(len(mesh.faces)),
            bbox={
                "xmin": float(bounds[0][0]),
                "ymin": float(bounds[0][1]),
                "zmin": float(bounds[0][2]),
                "xmax": float(bounds[1][0]),
                "ymax": float(bounds[1][1]),
                "zmax": float(bounds[1][2]),
                "x_length": float(lengths[0]),
                "y_length": float(lengths[1]),
                "z_length": float(lengths[2]),
            },
            output_paths={path.suffix.upper().lstrip(".") or "mesh": str(normalized)},
        )
        report.save(self.report_path(path))
        return report


def import_mesh(path: Path) -> ImportReport:
    return MeshImporter(OUTPUT_DIR).import_file(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa STL/OBJ para viewer fallback.")
    parser.add_argument("path")
    args = parser.parse_args(argv)
    report = import_mesh(Path(args.path))
    print(report.to_markdown())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
