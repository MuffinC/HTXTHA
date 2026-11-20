#!/usr/bin/env bash
# Create a local Python virtual environment for the backend and install
# runtime + dev dependencies. Linux / macOS / Git Bash.
#
# Usage (from anywhere):  ./scripts/setup_backend.sh
# Then:                   source backend/.venv/bin/activate
#                         cd backend && pytest
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
PYTHON="${PYTHON:-python3}"

# The backend targets Python 3.12 (matches the Docker image and CI).
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)'; then
  echo "Python 3.12+ is required (found: $("$PYTHON" --version 2>&1)). Set PYTHON=/path/to/python3.12." >&2
  exit 1
fi

echo "Creating virtual environment in $BACKEND_DIR/.venv"
"$PYTHON" -m venv "$BACKEND_DIR/.venv"

# Git Bash on Windows puts executables in Scripts/, POSIX systems in bin/.
if [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  VENV_PY="$BACKEND_DIR/.venv/bin/python"
else
  VENV_PY="$BACKEND_DIR/.venv/Scripts/python"
fi

"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r "$BACKEND_DIR/requirements-dev.txt"

echo
echo "Done. Activate with: source backend/.venv/bin/activate (or backend/.venv/Scripts/activate on Git Bash)"
echo "Windows PowerShell users: if activation is blocked, first run (this session only):"
echo "  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass"
echo "Run the API (mock mode): cd backend && LLM_PROVIDER=mock DATA_DIR=./data uvicorn app.main:app --reload"
echo "Then open http://127.0.0.1:8000/api/health (use 127.0.0.1, not localhost: localhost may resolve to IPv6, which uvicorn does not listen on)."
echo "API docs: http://127.0.0.1:8000/api/docs"
