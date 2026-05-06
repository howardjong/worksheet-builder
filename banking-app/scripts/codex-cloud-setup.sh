#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
. "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .

if ! command -v plaid-notion-sync >/dev/null 2>&1; then
  echo "Expected CLI entrypoint 'plaid-notion-sync' was not installed." >&2
  exit 1
fi

plaid-notion-sync --help >/dev/null

if [ "${CODEX_RUN_VERIFY:-0}" = "1" ]; then
  python -m compileall -q src
  if find . -path './.venv' -prune -o \( -path './tests' -o -name 'test_*.py' -o -name '*_test.py' \) -print -quit | grep -q .; then
    if python -c "import pytest" >/dev/null 2>&1; then
      python -m pytest
    else
      python -m unittest discover
    fi
  else
    echo "No test files detected; compile verification completed."
  fi
fi
