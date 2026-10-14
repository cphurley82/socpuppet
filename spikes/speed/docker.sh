#!/usr/bin/env bash
# Runs run.sh in the devcontainer's image, which is what CI builds in
# (Ubuntu 24.04, GCC 13), for the speed spike's Docker columns.
#
#   spikes/speed/docker.sh amd64 --env docker-amd64-on-macpro
#   spikes/speed/docker.sh arm64 --env docker-arm64-on-air
#   spikes/speed/docker.sh amd64 --llvm --env docker-amd64-on-ubuntu \
#     --backends llvm --default-backend llvm \
#     --llvm-dir /usr/lib/llvm-19/lib/cmake/llvm
#
# The first argument is the image's architecture. The image is built the
# first time, as socpuppet-dev:<arch>, and under Rosetta on an Apple
# silicon Mac that is the slow part. --llvm, next, uses that image with
# LLVM 19 added (llvm.Dockerfile). Everything after goes to run.sh.
set -euo pipefail

arch="$1"
shift
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image="socpuppet-dev:$arch"
docker image inspect "$image" > /dev/null 2>&1 ||
  docker build --platform "linux/$arch" --tag "$image" \
    --file "$root/.devcontainer/Dockerfile" "$root/.devcontainer"
if [[ "${1:-}" == --llvm ]]; then
  shift
  docker image inspect "socpuppet-dev-llvm:$arch" > /dev/null 2>&1 ||
    docker build --platform "linux/$arch" --tag "socpuppet-dev-llvm:$arch" \
      --build-arg "BASE=$image" --file "$root/spikes/speed/llvm.Dockerfile" \
      "$root/spikes/speed"
  image="socpuppet-dev-llvm:$arch"
fi

# The label run.sh is given names the virtual environment, so that each
# column keeps its own between runs. uv's cache and its Pythons are kept
# in build/ too, so that nothing is fetched twice.
label=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  [[ "${args[$i]}" == --env ]] && label="${args[$((i + 1))]}"
done

# On Linux the bind mount keeps the container's user, so run as ours to
# leave nothing in build/ that only root can remove.
user=()
[[ "$(uname -s)" == Linux ]] && user=(--user "$(id -u):$(id -g)")

exec docker run --rm --platform "linux/$arch" ${user[@]+"${user[@]}"} \
  --volume "$root:/workspace" --workdir /workspace \
  --env HOME=/tmp \
  --env UV_PROJECT_ENVIRONMENT="/workspace/build/venv-$label" \
  --env UV_CACHE_DIR="/workspace/build/uv-cache-$arch" \
  --env UV_PYTHON_INSTALL_DIR="/workspace/build/uv-python-$arch" \
  --env UV_LINK_MODE=copy \
  "$image" bash -c 'uv sync --quiet && spikes/speed/run.sh "$@"' run.sh "${args[@]}"
