#!/usr/bin/env bash
# Install the built wheel into a clean environment and run the Python tests
# against the installed copy, from outside the source tree.
#
# Usage: tools/test_wheel.sh uv|pip dist/socpuppet-*.whl
set -euo pipefail

installer=$1
wheel=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
repo=$(cd "$(dirname "$0")/.." && pwd)
# A wheel is built for one Python version; install it under that same one.
python=$(cat "$repo/.python-version")
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

cp -r "$repo/tests/python" "$scratch/tests"
cd "$scratch"

case $installer in
  uv)
    uv venv --quiet --python "$python" venv
    uv pip install --quiet --python venv/bin/python "$wheel" pytest
    ;;
  pip)
    uv venv --quiet --python "$python" --seed venv
    venv/bin/python -m pip install --quiet "$wheel" pytest
    ;;
  *)
    echo "unknown installer: $installer (expected uv or pip)" >&2
    exit 2
    ;;
esac

venv/bin/python -m pytest tests
