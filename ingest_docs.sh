#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  ./run.sh --help >/dev/null || true
fi

.venv/bin/python -m app.rag_ingest_v2 "$@"
