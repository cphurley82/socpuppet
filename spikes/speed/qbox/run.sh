#!/usr/bin/env bash
# QBox's rows of the speed spike: builds QBox with tools/build_qbox.py if it
# is not installed, builds the spike's tests in a tree of their own linked
# with it (build/speed-qbox), runs each of the spike's loops three times on
# the qbox_cpu, and appends the lines to
# spikes/speed/results/<env>-qbox.jsonl. Natively on Linux, or in the
# devcontainer's image, which has QBox's packages.
#
#   spikes/speed/qbox/run.sh --env native-linux-x86_64
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
# Natively, cmake is the one uv installed for socpuppet.
command -v cmake > /dev/null 2>&1 ||
  export PATH="$repository/.venv/bin:$PATH"
results="$repository/spikes/speed/results/$env_label-qbox.jsonl"
host="$(uname -n)"
commit="$(git -C "$repository" -c safe.directory='*' rev-parse --short HEAD)"
qbox="$repository/build/qbox"
tree="$repository/build/speed-qbox"

if [[ ! -f "$qbox/install/lib/cmake/qbox-2.0/qboxConfig.cmake" ]]; then
  start=$(date +%s)
  "$repository/tools/build_qbox.py" > "$qbox.build.log" 2>&1 || {
    echo "qbox/run.sh: QBox did not build, see $qbox.build.log" >&2
    printf '{"host": "%s", "env": "%s", "commit": "%s", "cpu": "qbox", "mode": "deterministic", "status": "build-failed"}\n' \
      "$host" "$env_label" "$commit" >> "$results"
    exit 1
  }
  printf '{"host": "%s", "env": "%s", "commit": "%s", "cpu": "qbox", "mode": "deterministic", "status": "qbox-build", "qbox_build_s": %s}\n' \
    "$host" "$env_label" "$commit" "$(($(date +%s) - start))" >> "$results"
fi
cmake --preset spike -B "$tree" -DSOCPUPPET_QBOX_DIR="$qbox/install" \
  -S "$repository" > "$tree.configure.log"
cmake --build "$tree" --target spike_speed_tests > "$tree.build.log"

binary="$tree/spikes/speed/spike_speed_tests"
qbox_commit="$(git -C "$qbox/src" -c safe.directory='*' rev-parse --short HEAD)"
for ((run = 1; run <= runs; run++)); do
  for test in $("$binary" --gtest_list_tests | sed -n 's/^  //p'); do
    # A test that crashes or is stopped by the alarm is a line that says
    # so, not the end of the run.
    line="$({ SPEED_HOST="$host" SPEED_ENV="$env_label" SPEED_COMMIT="$commit" \
      SPEED_RUN="$run" SOCPUPPET_CPU=qbox_cpu \
      perl -e "alarm 600; exec @ARGV" "$binary" \
      --gtest_filter="Speed.$test" 2>&1 || true; } |
      sed -n 's/^\[speed\] //p')"
    if [[ -z "$line" ]]; then
      line="{\"host\": \"$host\", \"env\": \"$env_label\", \"commit\": \"$commit\", \"cpu\": \"qbox\", \"mode\": \"deterministic\", \"status\": \"speed-failed\", \"test\": \"$test\", \"run\": $run}"
    else
      line="{\"status\": \"speed\", \"qbox\": \"$qbox_commit\", ${line#\{}"
    fi
    echo "$line" | tee -a "$results"
  done
done
