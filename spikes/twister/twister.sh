#!/usr/bin/env bash
# Runs Zephyr's twister against socpuppet's boards, with socpuppet as the
# emulator. Everything after the script's own options goes to twister:
#
#   spikes/twister/twister.sh -p socpuppet_host -T tests/kernel/common -v
#   spikes/twister/twister.sh --suites -p socpuppet_host     (all of suites.txt)
#
# A -T path that is relative is taken under Zephyr's tree, unless it starts
# with spikes/, which is this repository.
#
# It wants what firmware/build.sh leaves in build/firmware (the SDK, Zephyr,
# a venv) and a socpuppet built for Linux. On an Intel Mac it runs itself
# in the devcontainer's image, as firmware/build.sh does, since the SDK has
# no toolchain for one.
#
# On the Mac, Zephyr, the SDK, a venv and twister's output live on a Docker
# volume (socpuppet-twister), because the compiler reading them through
# Docker's file sharing is what made a scenario take a minute. They are
# copied there from build/firmware the first time and when the versions
# change. Only the verdicts and the logs come back, to build/twister/out.
# SOCPUPPET_TWISTER_BIND=1 runs everything on the bind mount instead, and
# SOCPUPPET_TWISTER_CCACHE=1 installs ccache in the container and keeps
# its cache on the volume: both exist so that the two can be measured.
set -euo pipefail

repository=$(cd "$(dirname "$0")/../.." && pwd)

if [[ "$(uname -s)-$(uname -m)" == Darwin-x86_64 ]]; then
  docker image inspect socpuppet-dev > /dev/null 2>&1 ||
    docker build --tag socpuppet-dev \
      --file "${repository}/.devcontainer/Dockerfile" "${repository}/.devcontainer"
  volume=()
  if [[ -z ${SOCPUPPET_TWISTER_BIND:-} ]]; then
    volume=(--volume socpuppet-twister:/twister --env SOCPUPPET_TWISTER_HOME=/twister)
  fi
  # The venv and its Python both live under build/, as firmware/build.sh
  # keeps them, so that they outlive the container.
  exec docker run --rm --volume "${repository}:/workspace" --workdir /workspace \
    --env UV_PROJECT_ENVIRONMENT=/workspace/build/linux-venv \
    --env UV_PYTHON_INSTALL_DIR=/workspace/build/firmware/python \
    --env SOCPUPPET_TWISTER_CCACHE ${volume[@]+"${volume[@]}"} \
    socpuppet-dev spikes/twister/twister.sh "$@"
fi

firmware=${repository}/build/firmware
for each in "${firmware}/zephyr" "${firmware}/venv/bin/python" "${firmware}/zephyr-sdk-1.0.1"; do
  [[ -e ${each} ]] || { echo "Run firmware/build.sh first: ${each} is missing" >&2; exit 1; }
done

# socpuppet for this machine, in build/linux (docs/development.md has the
# same recipe), built again each run so that the .so the runner imports is
# the tree's. A venv whose Python was in a container that is gone is made
# again, and the build with it: its cache names that Python's headers, and
# configuring again on top of fetched sources applies their patches twice.
(
  cd "${repository}"
  environment=${UV_PROJECT_ENVIRONMENT:-${repository}/.venv}
  if ! "${environment}/bin/python" -c '' > /dev/null 2>&1; then
    echo "The Linux venv's Python is gone: making it and build/linux again"
    rm -rf "${environment}" build/linux
    uv sync --quiet
  fi
  [[ -f build/linux/CMakeCache.txt ]] ||
    uv run cmake -S . -B build/linux -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
      -DSOCPUPPET_DEVELOPER_MODE=ON > /dev/null
  uv run cmake --build build/linux | tail -n 1
)

# What twister imports beyond what the build needs: the small part of
# scripts/requirements-build-test.txt and requirements-run-test.txt that
# it actually loads. Not the whole of either, which pull in gcovr, mypy,
# opencv and pyocd.
twister_needs=(psutil tabulate natsort anytree junitparser colorama ply
  pyserial pytest packaging python-dotenv)
twister_imports="import psutil, tabulate, natsort, anytree, junitparser, colorama, ply, serial, pytest, packaging, dotenv"

# Where Zephyr, the SDK, the venv and the output live: build/firmware and
# build/twister, or the volume. A stamp of the versions says whether the
# volume's copy is the one build/firmware has.
home=${SOCPUPPET_TWISTER_HOME:-}
if [[ -n ${home} ]]; then
  stamp="$(git -C "${firmware}/zephyr" describe --tags --always 2> /dev/null || echo unknown) zephyr-sdk-1.0.1"
  if [[ ! -f ${home}/stamp || "$(cat "${home}/stamp")" != "${stamp}" ]]; then
    echo "Copying Zephyr and the SDK to the volume (once per version)"
    rm -rf "${home}/zephyr" "${home}/zephyr-sdk-1.0.1" "${home}/venv" "${home}/.west"
    tar -C "${firmware}" --exclude=zephyr/.git -cf - zephyr zephyr-sdk-1.0.1 | tar -C "${home}" -xf -
    (cd "${home}" && "${firmware}/venv/bin/west" init --local zephyr > /dev/null 2>&1)
    echo "${stamp}" > "${home}/stamp"
  fi
  if ! "${home}/venv/bin/python" -c "${twister_imports}" > /dev/null 2>&1; then
    echo "Making the volume's venv"
    rm -rf "${home}/venv"
    UV_PYTHON_INSTALL_DIR=${home}/python uv venv --quiet --python-preference only-managed "${home}/venv"
    uv pip install --quiet --python "${home}/venv/bin/python" \
      --requirement "${home}/zephyr/scripts/requirements-base.txt" cmake ninja "${twister_needs[@]}"
  fi
  zephyr=${home}/zephyr
  sdk=${home}/zephyr-sdk-1.0.1
  venv=${home}/venv
  module=${home}/module
  outdir=${home}/out
else
  zephyr=${firmware}/zephyr
  sdk=${firmware}/zephyr-sdk-1.0.1
  venv=${firmware}/venv
  module=${repository}/build/twister/module
  outdir=${repository}/build/twister/out
  "${venv}/bin/python" -c "${twister_imports}" 2> /dev/null ||
    uv pip install --quiet --python "${venv}/bin/python" "${twister_needs[@]}"
fi

# ccache, when asked for: Zephyr's build uses it by itself when it is on
# the PATH (cmake/modules/ccache.cmake).
if [[ -n ${SOCPUPPET_TWISTER_CCACHE:-} ]]; then
  command -v ccache > /dev/null ||
    { apt-get update > /dev/null && apt-get install -y --no-install-recommends ccache > /dev/null; }
  export CCACHE_DIR=${home:-${repository}/build/twister}/ccache
  ccache --zero-stats > /dev/null
else
  export USE_CCACHE=0
fi

# The module, copied, with the spike's twister files added to each board.
# The real module is not touched: nothing outside spikes/ depends on this.
rm -rf "${module}"
mkdir -p "$(dirname "${module}")"
cp -R "${repository}/python/socpuppet/zephyr_module" "${module}"
for board in socpuppet_host socpuppet_ssd socpuppet_iomgr; do
  cp "${repository}/spikes/twister/boards/${board}/"* "${module}/boards/socpuppet/${board}/"
  # Zephyr's watchdog test looks for the alias `watchdog0`, which the
  # generated devicetrees do not have. A devicetree may say `/ { }` twice.
  cat "${repository}/spikes/twister/overlays/watchdog0_${board}.overlay" \
    >> "${module}/boards/socpuppet/${board}/${board}.dts"
done

export ZEPHYR_BASE=${zephyr}
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export ZEPHYR_SDK_INSTALL_DIR=${sdk}
export ZEPHYR_EXTRA_MODULES=${module}
export PATH=${repository}/spikes/twister/bin:${venv}/bin:${PATH}
export PYTHONPATH=${repository}/python
# socpuppet has no dependencies, so Zephyr's own venv runs it: its Python
# is the 3.13 the Linux .so was built for, and it outlives the container.
export SOCPUPPET_PYTHON=${venv}/bin/python
export SOCPUPPET_FIRMWARE_DIR=${firmware}

# A -T that is relative is Zephyr's, or ours if it starts with spikes/.
resolve() {
  case $1 in
    /*) echo "$1" ;;
    spikes/*) echo "${repository}/$1" ;;
    *) echo "${zephyr}/$1" ;;
  esac
}

run_twister() {
  local arguments=()
  while (($#)); do
    case $1 in
      -T|--testsuite-root) arguments+=("$1" "$(resolve "$2")"); shift 2 ;;
      -T*) arguments+=("-T" "$(resolve "${1#-T}")"); shift ;;
      *) arguments+=("$1"); shift ;;
    esac
  done
  "${venv}/bin/python" "${zephyr}/scripts/twister" \
    --outdir "${outdir}" --no-detailed-test-id "${arguments[@]}"
}

# Twister's verdicts and logs come back from the volume; the builds stay.
bring_back() {
  [[ -n ${home} && -d ${outdir} ]] || return 0
  local back=${repository}/build/twister/out
  rm -rf "${back}"
  mkdir -p "${back}"
  (cd "${outdir}" &&
    find . \( -name '*.json' -o -name '*.xml' -o -name handler.log -o -name build.log \) -print0 |
    tar --null -T - -cf -) | tar -C "${back}" -xf -
  echo "Verdicts and logs: build/twister/out"
}

status=0
if [[ ${1:-} == --suites ]]; then
  shift
  # Every suite in suites.txt in one run, except the ones that need -K,
  # which get a run each so that the flag forces nothing else onto a board
  # that excludes it.
  plain=()
  while read -r suite flags; do
    [[ -n ${suite} && ${suite} != \#* ]] || continue
    if [[ -z ${flags} ]]; then
      plain+=(-T "${suite}")
    else
      echo "=== ${suite} ${flags}"
      # shellcheck disable=SC2086
      run_twister -T "${suite}" ${flags} "$@" || status=$?
    fi
  done < "${repository}/spikes/twister/suites.txt"
  echo "=== ${plain[*]}"
  run_twister "${plain[@]}" "$@" || status=$?
else
  run_twister "$@" || status=$?
fi
[[ -z ${SOCPUPPET_TWISTER_CCACHE:-} ]] || ccache --show-stats | grep -E "Hits|Misses|Cache size" | head -4
bring_back
exit ${status}
