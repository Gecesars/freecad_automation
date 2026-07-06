from __future__ import annotations

from pathlib import Path

from app.importers.import_report import ImportReport
from app.settings import OUTPUT_DIR


class BaseImporter:
    name = "base"

    def __init__(self, output_dir: Path = OUTPUT_DIR) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def import_file(self, path: Path, **kwargs) -> ImportReport:
        raise NotImplementedError

    def report_path(self, source_path: Path) -> Path:
        return self.output_dir / f"{source_path.stem}_{self.name}_import_report.md"


def bbox_from_points(points: list[tuple[float, float]]) -> dict[str, float]:
    if not points:
        return {"xmin": 0.0, "ymin": 0.0, "xmax": 0.0, "ymax": 0.0, "x_length": 0.0, "y_length": 0.0}
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    return {
        "xmin": float(xmin),
        "ymin": float(ymin),
        "xmax": float(xmax),
        "ymax": float(ymax),
        "x_length": float(xmax - xmin),
        "y_length": float(ymax - ymin),
    }
