#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

echo "==> uv sync --all-extras --all-packages --dev"
uv sync --all-extras --all-packages --dev

echo "==> pre-commit install"
uv run pre-commit install

echo "Dev environment ready."
