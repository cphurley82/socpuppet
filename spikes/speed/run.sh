#!/usr/bin/env bash
# The speed spike's runner (milestone M26). Builds a tree of its own for
# one environment, times what a developer waits for in it, runs the speed
# tests three times, and appends every line to results/. See README.md.
#
#   spikes/speed/run.sh --env native-macos-x86_64
#   spikes/speed/run.sh --env native-linux-x86_64 --backends asmjit \
#     --default-backend asmjit
#
# Options:
#   --env LABEL            where this runs; one of the labels below
#   --backends LIST        DBT-RISE's backends to build besides the
#                          interpreter, separated by ';'
#   --default-backend NAME the backend the CPU uses when nothing says
#   --llvm-dir DIR         where LLVM's CMake package is, for --backends llvm
#   --runs N               how many times to run the speed tests (3)
#   --no-rebuild           skip timing the build from nothing and the
#                          incremental one
#   --no-suite             skip the dev suite
#   --jobs N               how many compiler jobs (all the machine has)
#   --dbt-rise-jobs N      how many of DBT-RISE's generated files to compile
#                          at once (4); each wants over a gigabyte
#   --sources-from TREE    take the dependencies' sources, already fetched
#                          and patched, from another tree's _deps instead of
#                          fetching them: for when GitHub cannot be reached.
#                          Everything is still compiled in this tree
set -euo pipefail

readonly LABELS=(
  native-macos-x86_64 docker-amd64-on-macpro
  native-macos-arm64 docker-arm64-on-air docker-amd64-rosetta-on-air
  native-linux-x86_64 docker-amd64-on-ubuntu
)

env_label=""
backends=""
default_backend=""
llvm_dir=""
runs=3
rebuild=1
suite=1
jobs=""
dbt_rise_jobs=""
sources_from=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) env_label="$2"; shift 2 ;;
    --backends) backends="$2"; shift 2 ;;
    --default-backend) default_backend="$2"; shift 2 ;;
    --llvm-dir) llvm_dir="$2"; shift 2 ;;
    --runs) runs="$2"; shift 2 ;;
    --no-rebuild) rebuild=0; shift ;;
    --no-suite) suite=0; shift ;;
    --jobs) jobs="$2"; shift 2 ;;
    --dbt-rise-jobs) dbt_rise_jobs="$2"; shift 2 ;;
    --sources-from) sources_from="$2"; shift 2 ;;
    *) echo "run.sh: unknown option $1 (see the top of this file)" >&2; exit 2 ;;
  esac
done

known=0
for label in "${LABELS[@]}"; do [[ "$label" == "$env_label" ]] && known=1; done
if [[ $known -eq 0 ]]; then
  echo "run.sh: --env must be one of: ${LABELS[*]}" >&2
  echo "  (got '${env_label}'). The label says where a result came from," >&2
  echo "  and collect.py refuses any other." >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
tag="$env_label"
[[ -n "$backends" ]] && tag="$tag-${backends//;/-}"
[[ -n "$default_backend" ]] && tag="$tag-default-$default_backend"
# Which LLVM, from where its package is: llvm-19 for /usr/lib/llvm-19/...,
# llvm@22 for Homebrew's /usr/local/opt/llvm@22/...
llvm=""
if [[ -n "$llvm_dir" ]]; then
  llvm="$(basename "$(dirname "$(dirname "$(dirname "$llvm_dir")")")")"
  tag="$tag-$llvm"
fi
tree="build/speed-$tag"
results="spikes/speed/results/$tag.jsonl"
mkdir -p spikes/speed/results

host="$(uname -n)"
commit="$(git -c safe.directory='*' rev-parse --short HEAD)"
if [[ -n "$(git -c safe.directory='*' status --porcelain --untracked-files=no)" ]]; then
  commit="$commit+dirty"
fi
if [[ "$(uname -s)" == Darwin ]]; then
  cpu_model="$(sysctl -n machdep.cpu.brand_string)"
  threads="$(sysctl -n hw.ncpu)"
else
  cpu_model="$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)"
  [[ -z "$cpu_model" ]] && cpu_model="$(uname -m)"
  threads="$(nproc)"
fi
jobs="${jobs:-$threads}"

# The extension is built into the source tree, python/socpuppet/, by
# whichever tree built last. Keep the one that was there and put it back.
saved="$(mktemp -d)"
cp python/socpuppet/_core.*.so "$saved"/ 2>/dev/null || true
restore() {
  local status=$?
  [[ $status -ne 0 ]] && echo "run.sh: stopped by a failure (status $status)" >&2
  rm -f python/socpuppet/_core.*.so
  cp "$saved"/_core.*.so python/socpuppet/ 2>/dev/null || true
  rm -rf "$saved"
}
trap restore EXIT

# Seconds, to the hundredth. perl, because macOS's bash and date have no
# clock finer than a second and the dev container has no python3 outside
# uv's environment.
now() { perl -MTime::HiRes=time -e 'printf "%.2f\n", time'; }
since() { perl -e "printf '%.2f', $(now) - $1"; }

# One line of results/, with what every line carries.
emit() {
  printf '{"host": "%s", "env": "%s", "commit": "%s", "cpu_model": "%s", "threads": %s, "backends": "%s", "default_backend": "%s", "llvm": "%s", %s}\n' \
    "$host" "$env_label" "$commit" "$cpu_model" "$threads" "$backends" \
    "${default_backend:-interp}" "$llvm" "$1" | tee -a "$results"
}

configure_args=(--preset spike -B "$tree" -DSOCPUPPET_BUILD_SPIKES=ON)
[[ -n "$backends" ]] && configure_args+=("-DSOCPUPPET_DBT_RISE_BACKENDS=$backends")
[[ -n "$default_backend" ]] && configure_args+=("-DSOCPUPPET_DBT_RISE_DEFAULT_BACKEND=$default_backend")
[[ -n "$llvm_dir" ]] && configure_args+=("-DSOCPUPPET_LLVM_DIR=$llvm_dir")
[[ -n "$dbt_rise_jobs" ]] && configure_args+=("-DSOCPUPPET_DBT_RISE_JOBS=$dbt_rise_jobs")
if [[ -n "$sources_from" ]]; then
  for source in "$sources_from"/_deps/*-src; do
    # FetchContent's name upper-cased, hyphens and all: YAML-CPP.
    name="$(basename "$source" -src | tr '[:lower:]' '[:upper:]')"
    # SPDK's one header is fetched into a directory of its own inside, so
    # that it is included as "spdk/nvme_spec.h" (cmake/Dependencies.cmake).
    [[ -d "$source/spdk" ]] && source="$source/spdk"
    configure_args+=("-DFETCHCONTENT_SOURCE_DIR_$name=$(cd "$source" && pwd)")
  done
fi

echo "🧦 speed: $tag in $tree"
start="$(now)"
# Every tree fetches its dependencies, so a dropped connection to GitHub
# fails a configure: try three times, a minute apart.
for attempt in 1 2 3; do
  uv run cmake "${configure_args[@]}" > "$tree.configure.log" 2>&1 && break
  [[ $attempt -lt 3 ]] && sleep 60
done
grep -q "Generating done" "$tree.configure.log" || {
  echo "run.sh: configuring failed, see $tree.configure.log" >&2
  tail -20 "$tree.configure.log" >&2
  emit '"status": "configure-failed"'
  exit 1
}
configure_s="$(since "$start")"
# A configure from another tree's sources downloads nothing, so its time
# is not a configure from nothing.
[[ -n "$sources_from" ]] && configure_s=0

build() {
  uv run cmake --build "$tree" -j "$jobs" > "$tree.build.log" 2>&1
}
if [[ $rebuild -eq 1 ]]; then
  # Dependencies are fetched by the configure above, so the build from
  # nothing times compiling and linking and no network.
  uv run cmake --build "$tree" --target clean > /dev/null 2>&1 || true
  start="$(now)"
  build || {
    echo "run.sh: the build failed, see $tree.build.log" >&2
    tail -30 "$tree.build.log" >&2
    emit '"status": "build-failed"'
    exit 1
  }
  full_build_s="$(since "$start")"
  touch src/socpuppet/models/dbt_rise_cpu.cpp
  start="$(now)"
  build
  incremental_s="$(since "$start")"
  emit "\"status\": \"loop\", \"jobs\": $jobs, \"configure_s\": $configure_s, \"full_build_s\": $full_build_s, \"incremental_s\": $incremental_s"
else
  build || {
    echo "run.sh: the build failed, see $tree.build.log" >&2
    tail -30 "$tree.build.log" >&2
    emit '"status": "build-failed"'
    exit 1
  }
fi

binary="$tree/spikes/speed/spike_speed_tests"
sizes="\"speed_binary_bytes\": $(wc -c < "$binary" | tr -d ' ')"
for module in python/socpuppet/_core.*.so; do
  [[ "$module" -nt "$saved" ]] && sizes="$sizes, \"extension_bytes\": $(wc -c < "$module" | tr -d ' ')"
done
emit "\"status\": \"sizes\", $sizes"

if [[ $suite -eq 1 ]]; then
  start="$(now)"
  set +e
  # A test that hangs on a backend can print without end, and ctest keeps
  # what a test prints in memory: on the Ubuntu box it grew to 19 GB and
  # was killed. So it keeps the last megabyte of each.
  uv run ctest --test-dir "$tree" -j 8 -LE 'spike|speed' --timeout 300 \
    --test-output-size-passed 100000 --test-output-size-failed 1000000 \
    --test-output-truncation tail > "$tree.suite.log" 2>&1
  # ctest's timeout ends the test it started and not always the process
  # under it: a test that hung on a backend was found five hours later,
  # still at 100 % of a core, under the next column's timings.
  pkill -9 -f "^$tree/tests/" || true
  set -e
  suite_s="$(since "$start")"
  # "99% tests passed, 1 tests failed out of 925", or with none failed
  # "100% tests passed out of 925".
  summary="$(grep -E 'tests passed.* out of [0-9]+' "$tree.suite.log" | tail -1 || true)"
  total="$(echo "$summary" | sed -nE 's/.* out of ([0-9]+).*/\1/p')"
  failed="$(echo "$summary" | sed -nE 's/.* ([0-9]+) tests failed out of.*/\1/p')"
  skipped="$(grep -c '\*\*\*Skipped\|Not Run' "$tree.suite.log" || true)"
  names="$(sed -n '/The following tests FAILED/,$p' "$tree.suite.log" |
    sed -nE 's/^[[:space:]]*[0-9]+ - ([^ ]+) .*/\1/p' | tr '\n' ' ' | sed 's/ $//')"
  # The C++ tests, each in a process of its own, and pytest, which is one.
  cpp_s="$(sed -nE 's/^cpp +=  *([0-9.]+) sec.*/\1/p' "$tree.suite.log")"
  pytest_s="$(sed -nE 's/.*Test +#[0-9]+: pytest .* ([0-9.]+) sec/\1/p' "$tree.suite.log")"
  emit "\"status\": \"suite\", \"suite_s\": $suite_s, \"cpp_s\": ${cpp_s:-0}, \"pytest_s\": ${pytest_s:-0}, \"tests\": ${total:-0}, \"failed\": ${failed:-0}, \"skipped\": ${skipped:-0}, \"failed_names\": \"$names\""
fi

tests="$("$binary" --gtest_list_tests | sed -n 's/^  //p')"
# Not seq, which on macOS counts down from 1 to 0.
for ((run = 1; run <= runs; run++)); do
  for test in $tests; do
    line="$(SPEED_HOST="$host" SPEED_ENV="$env_label" SPEED_COMMIT="$commit" \
      SPEED_RUN="$run" "$binary" --gtest_filter="Speed.$test" 2>&1 |
      sed -n 's/^\[speed\] //p')"
    if [[ -z "$line" ]]; then
      emit "\"status\": \"speed-failed\", \"test\": \"$test\", \"run\": $run"
    else
      # The test knows what it ran; this adds what it ran on.
      echo "{\"cpu_model\": \"$cpu_model\", \"threads\": $threads, \"backends\": \"$backends\", \"llvm\": \"$llvm\", \"status\": \"speed\", ${line#\{}" |
        tee -a "$results"
    fi
  done
done
echo "✅ speed: $tag done, lines in $results"
