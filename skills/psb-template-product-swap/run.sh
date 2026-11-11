#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${PSB_PYTHON:-}" ]; then PY="$PSB_PYTHON";
else PY=python3; fi
exec "$PY" "$HERE/scripts/render_sku.py" "$@"
