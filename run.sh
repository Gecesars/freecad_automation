#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENDOR_LIB="$PWD/vendor/lib/usr/lib/x86_64-linux-gnu"
if [ -d "$VENDOR_LIB" ]; then
  export LD_LIBRARY_PATH="$VENDOR_LIB:${LD_LIBRARY_PATH:-}"
fi

if [ ! -x .venv/bin/python ]; then
  if python3 -m venv .venv >/tmp/freecad_prompt_forge_venv.log 2>&1; then
    :
  else
    rm -rf .venv
    if ! python3 -m virtualenv .venv; then
      python3 -m pip install --user --break-system-packages virtualenv
      python3 -m virtualenv .venv
    fi
  fi
fi

.venv/bin/python -m pip install -r requirements.txt

if [ ! -s data/rag/chunks_v2.json ]; then
  .venv/bin/python -m app.rag_ingest_v2
fi

exec .venv/bin/python -m app.main "$@"
