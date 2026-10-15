#!/usr/bin/env bash
# Runs a command in the devcontainer's image, which is Linux with GCC and
# what CI builds in, with the repository at /workspace:
#
#   tools/devcontainer.sh uv run cmake --preset qbox
#   tools/devcontainer.sh bash
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dockerfile="$repository/.devcontainer/Dockerfile"

# The image is named after its Dockerfile's contents, so a change to the
# Dockerfile builds it again. It is socpuppet-dev too, the name
# firmware/build.sh and firmware/twister.sh look for.
if command -v sha256sum > /dev/null; then
  hash="$(sha256sum "$dockerfile")"
else
  hash="$(shasum --algorithm 256 "$dockerfile")"
fi
image="socpuppet-dev:${hash:0:12}"
docker image inspect "$image" > /dev/null 2>&1 ||
  docker build --tag "$image" --tag socpuppet-dev \
    --file "$dockerfile" "$(dirname "$dockerfile")"

# QBox's tree and socpuppet's tree built with it are Docker volumes, at the
# places in build/ that tools/build_qbox.sh and the qbox preset use: a
# compiler reading through the repository's mount from a Mac is ten times
# slower (docs/twister-spike.md). On the Mac those two directories stay
# empty, and `docker volume rm socpuppet-qbox socpuppet-qbox-dev` throws
# the trees away.
exec docker run --rm \
  --volume "$repository:/workspace" --workdir /workspace \
  --volume socpuppet-qbox:/workspace/build/qbox \
  --volume socpuppet-qbox-dev:/workspace/build/qbox-dev \
  "$image" "$@"
