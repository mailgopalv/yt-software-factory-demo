#!/usr/bin/env bash
# One-time setup on Mac (and Linux). Run from this folder:  ./setup.sh
# Safe to run again: it skips anything already done.
set -e
cd "$(dirname "$0")"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1. $2"; exit 1; }; }
need git "Install Git (xcode-select --install, or https://git-scm.com)"
need python3 "Install Python 3.11 or newer (https://www.python.org or Homebrew)"
need node "Install Node.js 20 or newer (https://nodejs.org or Homebrew)"
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || { echo "Python 3.11 or newer is needed."; exit 1; }

# 1. The store is its own git repo (the factory branches, merges and tags it), shipped as store.bundle.
if [ ! -d store/.git ]; then
  echo "Unpacking the Corner Shop store repo from store.bundle..."
  git clone --quiet store.bundle store
  git -C store remote remove origin
fi
chmod +x store/*.sh software-factory/*.sh

# 2. The store's Python and Node packages, the Playwright browser and the database.
./store/setup-store.sh

# 3. The factory's Python packages.
cd software-factory
if [ ! -x .venv/bin/python ]; then
  echo "Creating the factory's Python environment..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
fi
.venv/bin/python -m pip install --quiet -r requirements.txt
cd ..

echo ""
echo "Setup complete. Next, in two terminals:"
echo "  1) cd store && ./run-store.sh                       (store: http://localhost:5173)"
echo "  2) cd software-factory && ./run-factory.sh --demo   (dashboard: http://localhost:8000)"
