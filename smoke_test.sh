#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  ./run.sh --help >/dev/null || true
fi

.venv/bin/python -m app.main \
  --prompt "Crie uma placa de aluminio 120x80x6 mm com quatro furos de 6 mm nos cantos e um rasgo central de 40x12 mm." \
  --run-freecad

.venv/bin/python -m pytest -q
