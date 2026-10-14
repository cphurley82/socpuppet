#!/usr/bin/env bash
# QBox's rows of the speed spike: builds QBox into $QBOX_ROOT if it is not
# there, builds the loops against it, runs each three times, and appends
# the lines to spikes/speed/results/<env>-qbox.jsonl. Natively on Linux, or
# in spikes/iss/qbox/Dockerfile's image (README.md).
#
#   QBOX_ROOT=~/qbox spikes/speed/qbox/run.sh --env native-linux-x86_64
set -euo pipefail

env_label=""
runs=3
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) env_label="$2"; shift 2 ;;
    --runs) runs="$2"; shift 2 ;;
    *) echo "qbox/run.sh: unknown option $1" >&2; exit 2 ;;
  esac
done
case "$env_label" in
  native-macos-x86_64 | docker-amd64-on-macpro | native-macos-arm64 | \
    docker-arm64-on-air | docker-amd64-rosetta-on-air | \
    native-linux-x86_64 | docker-amd64-on-ubuntu) ;;
  *) echo "qbox/run.sh: --env must be one of run.sh's labels" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$here/../../.." && pwd)"
root="${QBOX_ROOT:-/qbox}"
# Natively, cmake is the one uv installed for socpuppet. In a container
# the image has its own, and the bind mount's is the host's.
command -v cmake > /dev/null 2>&1 ||
  export PATH="$repository/.venv/bin:$PATH"
results="$repository/spikes/speed/results/$env_label-qbox.jsonl"
host="$(uname -n)"
commit="$(git -C "$repository" -c safe.directory='*' rev-parse --short HEAD)"

if [[ ! -f "$root/src/build/install/lib/cmake/qbox/qboxConfig.cmake" &&
  ! -d "$root/src/build/install/lib/cmake" ]]; then
  start=$(date +%s)
  "$here/build.sh" > "$root.build.log" 2>&1 || {
    echo "qbox/run.sh: QBox did not build, see $root.build.log" >&2
    printf '{"host": "%s", "env": "%s", "commit": "%s", "cpu": "qbox", "mode": "deterministic", "status": "build-failed"}\n' \
      "$host" "$env_label" "$commit" >> "$results"
    exit 1
  }
  printf '{"host": "%s", "env": "%s", "commit": "%s", "cpu": "qbox", "mode": "deterministic", "status": "qbox-build", "qbox_build_s": %s}\n' \
    "$host" "$env_label" "$commit" "$(($(date +%s) - start))" >> "$results"
fi
cmake -S "$here" -B "$root/speed" -G Ninja \
  -DQBOX_ROOT="$root/src/build/install" > "$root/speed.configure.log"
cmake --build "$root/speed" > "$root/speed.build.log"

binary="$root/speed/spike_speed_qbox_tests"
qbox="$(git -C "$root/src" -c safe.directory='*' rev-parse --short HEAD)"
for ((run = 1; run <= runs; run++)); do
  for test in $("$binary" --gtest_list_tests | sed -n 's/^  //p'); do
    # A test that crashes or is stopped by the alarm is a line that says
    # so, not the end of the run.
    line="$({ SPEED_HOST="$host" SPEED_ENV="$env_label" SPEED_COMMIT="$commit" \
      SPEED_RUN="$run" perl -e "alarm 600; exec @ARGV" "$binary" \
      --gtest_filter="Qbox.$test" 2>&1 || true; } |
      sed -n 's/^\[speed\] //p')"
    if [[ -z "$line" ]]; then
      mode=deterministic
      [[ "$test" == *Threaded ]] && mode=threaded
      line="{\"host\": \"$host\", \"env\": \"$env_label\", \"commit\": \"$commit\", \"cpu\": \"qbox\", \"mode\": \"$mode\", \"status\": \"speed-failed\", \"test\": \"$test\", \"run\": $run}"
    else
      line="{\"status\": \"speed\", \"qbox\": \"$qbox\", ${line#\{}"
    fi
    echo "$line" | tee -a "$results"
  done
done
