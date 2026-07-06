from __future__ import annotations

import json

from app.workers.freecad_worker import FreeCADWorker


def main() -> int:
    def on_line(stream: str, line: str) -> None:
        print(f"[{stream}] {line}", end="" if line.endswith("\n") else "\n", flush=True)

    result = FreeCADWorker().run_minimal_test(force=True, on_line=on_line)
    print(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
