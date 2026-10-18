#!/usr/bin/env bash
# Restores the store code, its database and the factory's runs to a checkpoint, for re-shooting a scene.
#   ./reset-to.sh checkpoint-2-factory-added
# Run without a name to list the checkpoints.
cd "$(dirname "$0")"
if [ -z "$1" ]; then
  .venv/bin/python -m factory checkpoints
  exit 0
fi
.venv/bin/python -m factory reset-to "$1"
