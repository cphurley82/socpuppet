#!/usr/bin/env bash
# Runs a command in the devcontainer's image, which is Linux with GCC and
# what CI builds in, with the repository at /workspace:
#
#   tools/devcontainer.sh uv run cmake --preset qbox
#   tools/devcontainer.sh bash
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "usage: tools/devcontainer.sh COMMAND [ARGUMENT...]" >&2
  exit 2
fi
if ! command -v docker > /dev/null; then
  echo "tools/devcontainer.sh runs its command in the devcontainer's image, and found no Docker to do that with." >&2
  echo "Install Docker Desktop, start it, and run this again." >&2
  exit 1
fi

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

# uv's venv, its cache and its Pythons are kept in build/, so that they
# outlive the container. The venv and the Python are the ones
# firmware/twister.sh makes on an Intel Mac, so the two share them.
options=(
  --env UV_PROJECT_ENVIRONMENT=/workspace/build/linux-venv
  --env UV_PYTHON_INSTALL_DIR=/workspace/build/firmware/python
  --env UV_CACHE_DIR=/workspace/build/linux-uv-cache
)
# And socpuppet's own variables, such as SOCPUPPET_REQUIRE_FIRMWARE and
# SOCPUPPET_CPU, go in with the command.
for name in $(compgen -e); do
  if [[ "$name" == SOCPUPPET_* ]]; then
    options+=(--env "$name=${!name}")
  fi
done

# On Linux the repository's mount keeps the container's user, so the command
# runs as the caller's, to leave nothing in build/ that only root can
# remove. Docker Desktop on a Mac does that mapping by itself.
if [[ "$(uname -s)" == Linux ]]; then
  options+=(--user "$(id -u):$(id -g)")
fi

# From a terminal, the command has one, so that a shell in the container
# works.
if [[ -t 0 && -t 1 ]]; then
  options+=(--interactive --tty)
fi

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
  "${options[@]}" "$image" "$@"
