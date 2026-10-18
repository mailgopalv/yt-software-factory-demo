#!/usr/bin/env bash
# Starts the AI Software Factory server and dashboard on http://localhost:8000
#   ./run-factory.sh          real agents (your Claude subscription)
#   ./run-factory.sh --demo   demo mode: replays the recordings in demo/, no Claude usage
# Press Ctrl+C to stop the server. A run already in progress keeps going in the background.
set -e
cd "$(dirname "$0")"
PYTHON=.venv/bin/python

if [ ! -x "$PYTHON" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv
  $PYTHON -m pip install --quiet --upgrade pip
fi
$PYTHON -m pip install --quiet -r requirements.txt

if [ "$1" = "--demo" ]; then export DEMO_MODE=1; else unset DEMO_MODE; fi

echo ""
echo "  Factory dashboard: http://localhost:8000"
echo "  Factory API docs:  http://localhost:8000/docs"
[ "$DEMO_MODE" = "1" ] && echo "  DEMO MODE: replaying recordings, no Claude usage"
echo ""
$PYTHON -m uvicorn server.app:app --host 127.0.0.1 --port 8000
