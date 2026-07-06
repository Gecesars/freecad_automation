#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  make install
fi
. .venv/bin/activate
python -m app.main \
  --prompt "placa de aluminio 120x80x6 mm com quatro furos de 6 mm nos cantos e rasgo central de 40x12 mm" \
  --run-freecad
