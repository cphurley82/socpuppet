#!/usr/bin/env bash
# Runs the steps of CI's jobs (.github/workflows/ci.yml and qbox.yml) on this
# machine, so that a push does not have to be the first time they run:
#
#   tools/ci_local.sh                  # every job, in the workflows' order
#   tools/ci_local.sh lint tidy        # just those
#   tools/ci_local.sh --clean test     # drop the patched dependencies first
#
# The jobs are lint, firmware, test, tidy, twister, coverage, sanitizers,
# qbox, wheel and devcontainer. A step that fails ends its job, and the jobs
# after it still run, as they do in CI. A summary at the end says what passed,
# and each step's output is in build/ci-local/<job>-<step>.log.
#
# This is your machine and not CI's runner, so a difference between the two
# (a newer GCC, say) shows up here as a failure, which is the point. The Linux
# packages are the ones docs/setup.md lists, and QBox's are in the qbox job's
# `apt-get install` in qbox.yml.
#
# 💡 The dev, coverage and sanitizers jobs share one build tree, so they run
# one after another, and the script puts the dev configuration back after
# them, as docs/development.md says to.
#
# ⚠️ git apply does not apply a patch twice. A build tree whose dependencies
# were patched by an older set of patches fails to configure with "patch does
# not apply". The script keeps a hash of the patches in build/, and when it
# has changed, or there is none, it deletes the dependencies that are patched
# (the ones with a PATCH_COMMAND in cmake/Dependencies.cmake, and QBox's
# rpclib) so that they are fetched and patched again. --clean does the same
# whatever the hash says.
set -uo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository" || exit 1

all_jobs=(lint firmware test tidy twister coverage sanitizers qbox wheel
  devcontainer)
logs="$repository/build/ci-local"
stamp="$repository/build/.ci-local-patches"

usage() {
  {
    echo "usage: tools/ci_local.sh [--clean] [JOB...]"
    echo "jobs: ${all_jobs[*]}"
    echo "With no job, every one is run."
  } >&2
  exit 2
}

clean=0
selected=()
for argument in "$@"; do
  case "$argument" in
    --clean) clean=1 ;;
    -h | --help) usage ;;
    -*) usage ;;
    *)
      known=0
      for job in "${all_jobs[@]}"; do
        [[ $job == "$argument" ]] && known=1
      done
      [[ $known == 1 ]] || usage
      selected+=("$argument")
      ;;
  esac
done
[[ ${#selected[@]} -gt 0 ]] || selected=("${all_jobs[@]}")

wants() {
  local job
  for job in "${selected[@]}"; do
    [[ $job == "$1" ]] && return 0
  done
  return 1
}

# ---------------------------------------------------------------------------
# Stale dependencies

patches_hash() {
  cat "$repository/cmake/Dependencies.cmake" \
    "$repository"/cmake/patches/* \
    "$repository/tools/build_qbox.sh" | sha256sum | cut -d' ' -f1
}

# The names of the dependencies that cmake/Dependencies.cmake patches: the
# FetchContent_Declare each PATCH_COMMAND sits in. FetchContent lowercases
# them in the directories it makes.
patched_dependencies() {
  awk '
    /FetchContent_Declare\(/ {
      name = $0
      sub(/.*FetchContent_Declare\(/, "", name)
      sub(/[ )].*/, "", name)
    }
    /PATCH_COMMAND/ { print tolower(name) }
  ' "$repository/cmake/Dependencies.cmake" | sort -u
}

drop_dependency() {
  local deps=$1 name=$2 suffix
  for suffix in src build subbuild; do
    rm -rf "${deps:?}/${name:?}-$suffix"
  done
}

drop_stale_dependencies() {
  local current previous=""
  current="$(patches_hash)"
  [[ -f $stamp ]] && previous="$(cat "$stamp")"
  if [[ $clean == 0 && $current == "$previous" ]]; then
    return
  fi
  echo "🧹 The patches have changed since the build trees were made (or there"
  echo "   is no record of them): dropping the dependencies that are patched,"
  echo "   so that they are fetched and patched again."
  local name tree
  for tree in build/dev build/qbox-dev; do
    while read -r name; do
      drop_dependency "$repository/$tree/_deps" "$name"
    done < <(patched_dependencies)
  done
  # QBox's own patches to rpclib, which CPM applies with `git am` (and
  # which, applied twice, stops the configure). libqemu is left alone: it is
  # the slow one, and tools/build_qbox.sh keeps its own patches.
  drop_dependency "$repository/build/qbox/build/_deps" rpclib
  mkdir -p "$(dirname "$stamp")"
  echo "$current" > "$stamp"
}

# ---------------------------------------------------------------------------
# Running steps

results=()
failed=0
current_job=""

# step LABEL COMMAND...: runs a command with its output in a log, and fails
# its job if the command does.
step() {
  local label=$1
  shift
  local log="$logs/$current_job-$label.log"
  local start=$SECONDS
  printf '   ▶ %-28s' "$label"
  if "$@" > "$log" 2>&1; then
    printf '✅ %ss\n' "$((SECONDS - start))"
    return 0
  fi
  printf '❌ %ss\n' "$((SECONDS - start))"
  echo "     output: $log"
  tail -n 15 "$log" | sed 's/^/     | /'
  return 1
}

run_job() {
  current_job=$1
  echo "🧦 $current_job"
  local start=$SECONDS
  if run_selected_job "$current_job"; then
    results+=("✅ $current_job ($((SECONDS - start))s)")
  else
    results+=("❌ $current_job ($((SECONDS - start))s)")
    failed=1
  fi
}

# The jobs are called by name from here, so that each is plainly in use.
run_selected_job() {
  case "$1" in
    lint) job_lint ;;
    firmware) job_firmware ;;
    test) job_test ;;
    tidy) job_tidy ;;
    twister) job_twister ;;
    coverage) job_coverage ;;
    sanitizers) job_sanitizers ;;
    qbox) job_qbox ;;
    wheel) job_wheel ;;
    devcontainer) job_devcontainer ;;
  esac
}

skip_job() {
  results+=("⏭  $1: ${*:2}")
  echo "⏭  $1: ${*:2}"
}

# ---------------------------------------------------------------------------
# The jobs, each the steps of the workflow's job of the same name.

job_lint() {
  step sync uv sync || return 1
  step lint uv run python tools/lint.py
}

job_firmware() {
  step build firmware/build.sh
}

job_test() {
  step configure uv run cmake --preset dev || return 1
  step build uv run cmake --build --preset dev || return 1
  # A missing firmware image fails its boot test instead of skipping it.
  step ctest env SOCPUPPET_REQUIRE_FIRMWARE=1 uv run ctest --preset dev
}

job_tidy() {
  step sync uv sync || return 1
  step configure uv run cmake --preset dev || return 1
  step tidy uv run cmake --build --preset dev --target tidy || return 1
  step check_headers uv run cmake --build --preset dev --target check_headers
}

job_twister() {
  step sync uv sync || return 1
  step configure uv run cmake --preset dev || return 1
  step build uv run cmake --build --preset dev || return 1
  step boards uv run pytest tests/python/test_twister_boards.py || return 1
  step tooling uv run pytest tests/tooling -k twister || return 1
  step twister firmware/twister.sh --suites
}

job_coverage() {
  step sync uv sync || return 1
  step configure uv run cmake --preset coverage || return 1
  step coverage uv run cmake --build --preset coverage --target coverage
}

job_sanitizers() {
  step sync uv sync || return 1
  step configure uv run cmake --preset asan || return 1
  step build uv run cmake --build --preset asan || return 1
  step ctest uv run ctest --preset asan
}

job_qbox() {
  if [[ $(uname -s) != Linux ]]; then
    echo "   (no clang-tidy step: it is Linux's, as in qbox.yml)"
  fi
  step sync uv sync || return 1
  step build_qbox uv run tools/build_qbox.sh || return 1
  step firmware firmware/build.sh || return 1
  step configure uv run cmake --preset qbox || return 1
  step build uv run cmake --build --preset qbox || return 1
  step ctest env SOCPUPPET_REQUIRE_FIRMWARE=1 uv run ctest --preset qbox ||
    return 1
  if [[ $(uname -s) == Linux ]]; then
    step tidy uv run cmake --build --preset qbox --target tidy || return 1
    step check_headers uv run cmake --build --preset qbox \
      --target check_headers || return 1
  fi
  step twister env SOCPUPPET_CPU=qbox_cpu \
    firmware/twister.sh --suites -p socpuppet_host
}

# build_wheel DIRECTORY TARGET OUTPUT: cibuildwheel in a copy of the tree.
# shellcheck disable=SC2329 # called through step
build_wheel() {
  (cd "$1" && uvx cibuildwheel --only "$2" --output-dir "$3")
}

job_wheel() {
  local tag platform checkout wheelhouse
  tag="cp$(tr -d . < .python-version)"
  case "$(uname -m)" in
    x86_64) platform=manylinux_x86_64 ;;
    aarch64 | arm64) platform=manylinux_aarch64 ;;
    *) platform=manylinux_x86_64 ;;
  esac
  wheelhouse="$logs/wheelhouse"
  # cibuildwheel copies the whole directory into its container, build/
  # included, so it is run from a copy of the tracked files and the new ones.
  checkout="$(mktemp -d)"
  rm -rf "$wheelhouse"
  git ls-files -z --cached --others --exclude-standard |
    xargs -0 cp --parents -t "$checkout" || return 1
  step cibuildwheel build_wheel "$checkout" "$tag-$platform" "$wheelhouse"
  local status=$?
  rm -rf "$checkout"
  [[ $status == 0 ]] || return 1
  local wheel
  for wheel in "$wheelhouse"/*.whl; do
    step check_wheel uv run --no-project python tools/check_wheel.py \
      "$wheel" || return 1
  done
  step test_wheel_uv env SOCPUPPET_REQUIRE_FIRMWARE=1 \
    SOCPUPPET_FIRMWARE_DIR="$repository/build/firmware" \
    tools/test_wheel.sh uv "$wheelhouse"/*-"$tag"-*.whl || return 1
  step test_wheel_pip env SOCPUPPET_REQUIRE_FIRMWARE=1 \
    SOCPUPPET_FIRMWARE_DIR="$repository/build/firmware" \
    tools/test_wheel.sh pip "$wheelhouse"/*-"$tag"-*.whl
}

job_devcontainer() {
  step image docker build -t socpuppet-dev .devcontainer || return 1
  # As CI does it: the checkout is the host user's and the container runs as
  # root, so git is told the mounted directory is safe to read.
  step tests docker run --rm -v "$repository:/workspace" -w /workspace \
    socpuppet-dev bash -c "git config --global --add safe.directory \
/workspace && uv sync && uv run cmake --preset dev && \
uv run cmake --build --preset dev && uv run ctest --preset dev"
}

# ---------------------------------------------------------------------------

mkdir -p "$logs"
drop_stale_dependencies

modes_changed=0
for job in "${all_jobs[@]}"; do
  wants "$job" || continue
  case "$job" in
    wheel | devcontainer)
      if ! command -v docker > /dev/null 2>&1; then
        skip_job "$job" "needs Docker, which is not installed"
        continue
      fi
      if ! docker info > /dev/null 2>&1; then
        skip_job "$job" "needs Docker, and \`docker info\` fails (is the" \
          "daemon running, and your user in the docker group?)"
        continue
      fi
      ;;
  esac
  if [[ $job == devcontainer ]] && [[ $(git ls-files -m -o --exclude-standard \
    .devcontainer | wc -l) == 0 ]] &&
    git diff --quiet main -- .devcontainer 2> /dev/null; then
    skip_job "$job" ".devcontainer is the same as main's, as in CI"
    continue
  fi
  run_job "$job"
  case "$job" in
    coverage | sanitizers) modes_changed=1 ;;
  esac
done

# The dev, coverage and asan presets share build/dev, which holds whichever
# was configured last.
if [[ $modes_changed == 1 ]]; then
  current_job=restore
  step dev_preset uv run cmake --preset dev > /dev/null || true
fi

echo
echo "🧦 Summary"
printf '   %s\n' "${results[@]}"
exit "$failed"
