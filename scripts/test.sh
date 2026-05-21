#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

MARKER_EXPR="${TERIDEX_TEST_MARKERS:-not integration}"
uv run pytest -m "$MARKER_EXPR" --cov=packages --cov=apps --cov-report=term-missing "$@"
