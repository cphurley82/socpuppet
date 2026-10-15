# Setting up a machine for development

This page takes a fresh machine to one that builds socpuppet, passes every test, builds the firmware the tests boot, and (if you want it) has QBox built and ready. It was last walked through from a bare Ubuntu 26.04 install, and every timing below comes from that run, on a 12-core, 24-thread AMD machine.

🧦 Once it is done, [Building and testing](development.md) is the everyday page.

## What gets installed, and by whom

```text
  apt / Homebrew  ──▶  the C++ compiler, git, zlib, dtc            (root, once)
                       QBox's build packages, if you want QBox
  uv              ──▶  Python 3.13, CMake, Ninja, pytest,          (your home, no root)
                       clang-format, clang-tidy, ruff, the linters
  cmake --preset  ──▶  SystemC, SCC, DBT-RISE, Boost and friends   (build/dev/_deps)
  firmware/build.sh ─▶  the Zephyr SDK, Zephyr, Zephyr's Python     (build/firmware)
  QBox's recipe   ──▶  QBox and its QEMU                           (~/qbox)
```

💡 Only the first row needs root. Everything else lives in your home directory or in the checkout, so deleting `build/` and `~/qbox` takes the machine back to where it started.

💡 **clang-format and clang-tidy come from uv, not from apt or Homebrew.** `pyproject.toml` pins them as Python wheels (`uv sync` installs them), so that every machine and CI format and check the code with exactly the same versions. A clang-format of another version formats some lines differently, and the lint check would fail on code that looks right to you. You do not need a system clang at all: the build uses GCC on Linux and Apple clang on a Mac.

## 1. System packages

### Ubuntu (24.04 or 26.04)

```sh
sudo apt-get update && sudo apt-get install -y \
  build-essential git curl xz-utils zlib1g-dev device-tree-compiler gdb
```

| Package | Why |
|---|---|
| `build-essential` | GCC and make. socpuppet needs C++20, which GCC 13 (24.04) and GCC 15 (26.04) both have |
| `git`, `curl`, `xz-utils` | fetching the dependencies at configure time, and the Zephyr SDK |
| `zlib1g-dev` | SCC's FST trace writer, which waveform viewers such as GTKWave open, needs it |
| `device-tree-compiler` | `dtc`, which checks the devicetrees socpuppet generates. Two tests skip without it |
| `gdb` | debugging the simulator. The firmware's own GDB comes with the Zephyr SDK |

For QBox (step 5), add its build packages now, while you have `sudo` to hand. They are the ones `spikes/iss/qbox/Dockerfile` installs:

```sh
sudo apt-get install -y \
  bison flex libasio-dev libelf-dev libepoxy-dev libglib2.0-dev \
  libjpeg-turbo8-dev libpixman-1-dev libsdl2-dev libslirp-dev \
  libvirglrenderer-dev libzip-dev lld llvm meson ninja-build \
  ocl-icd-opencl-dev pkg-config python3-dev python3-pip python3-venv
```

### macOS

```sh
xcode-select --install       # Apple clang, git, make
brew install dtc
```

⚠️ On an Intel Mac, `firmware/build.sh` needs [Docker Desktop](https://www.docker.com/products/docker-desktop/), because the Zephyr SDK has no toolchain for one. [development.md](development.md#firmware) has the details. QBox does not build natively on either kind of Mac today; it builds in a container (step 5).

## 2. uv

[uv](https://docs.astral.sh/uv/) manages Python and every tool the repository pins. It installs into your home directory:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

It adds `~/.local/bin` to your shell's start-up files, so open a new terminal (or `source ~/.local/bin/env`) before going on. On a Mac, `brew install uv` works too.

## 3. Build socpuppet and run the tests

```sh
git clone https://github.com/cphurley82/socpuppet && cd socpuppet
uv sync                                  # Python 3.13 and the tools
uv run cmake --preset dev                # fetch and configure the dependencies, about 100 s
uv run cmake --build --preset dev        # build, about 1 minute here
uv run ctest --preset dev                # every test, about 80 s
```

⚠️ The first configure and build take a few minutes, because SystemC, SCC, the CPU model and the parts of Boost they need are compiled from source. After that, builds are incremental.

At this point the boot tests that want firmware are skipped, and each says so. The next step gives them their firmware.

## 4. Build the firmware

```sh
firmware/build.sh                        # about 3 minutes the first time
```

The first run downloads the Zephyr SDK's RISC-V toolchain, Zephyr itself, and a Python for Zephyr's build scripts into `build/firmware` (about 2 GB on disk), then builds every image the tests boot. Later runs take seconds.

Now run the suite as CI does, where a missing image is a failure and not a skip:

```sh
SOCPUPPET_REQUIRE_FIRMWARE=1 uv run ctest --preset dev
```

✅ You should see `100% tests passed`, with nothing skipped.

## 5. QBox (optional)

🎓 [QBox](https://github.com/qualcomm/qbox) is Qualcomm's library for putting QEMU's CPUs inside a SystemC simulation. QEMU translates the guest's instructions into the host's instead of interpreting them, which makes it many times faster than socpuppet's default CPU. It is the second hart that [M27](plan.md#m27--qbox-the-second-hart-optional-built-from-source) is making into a CPU of socpuppet's.

🚧 Today QBox is built on its own, by the speed spike's recipe, and is not yet part of socpuppet's build: its SystemC cannot yet share a program with socpuppet's, which is M27's first step. So this step gets the machine ready for that work and lets you run the spike's QBox loops. When M27 lands, this section will name `tools/build_qbox.sh` and the `SOCPUPPET_QBOX_DIR` option instead.

⚠️ QEMU is GPL-2.0. QBox is always built from source beside socpuppet and never goes into the wheel.

On Linux, with the packages from step 1:

```sh
QBOX_ROOT=~/qbox JOBS=$(nproc) uv run spikes/speed/qbox/build.sh   # about 5 to 10 minutes
```

💡 `uv run` is there to put uv's CMake on the path for the recipe. QBox and its QEMU end up in `~/qbox` (about 3 GB), installed under `~/qbox/src/build/install`.

To see it run, build the speed spike's three loops against it and run one:

```sh
uv run cmake -S spikes/speed/qbox -B ~/qbox/speed -G Ninja \
  -DQBOX_ROOT=$HOME/qbox/src/build/install
uv run cmake --build ~/qbox/speed
~/qbox/speed/spike_speed_qbox_tests --gtest_filter=Qbox.CountedRepeatable
```

✅ It prints one `[speed]` line, several hundred million instructions a second, and `OK`.

⚠️ Run one test per process, as above. The SystemC kernel cannot be restarted, so the second test in the same process fails. `spikes/speed/qbox/run.sh` runs each test on its own and records the results, which is how the report's tables were made ([speed-spike.md](speed-spike.md)).

On a Mac, build it in the container instead:

```sh
docker build -t socpuppet-qbox spikes/iss/qbox
docker run --rm -v socpuppet-qbox:/qbox -v "$PWD:/workspace" -w /workspace \
  socpuppet-qbox spikes/speed/qbox/build.sh
```

## 6. Before your first push

CI runs two checks that `ctest` does not. Run them once now to be sure the toolchain is complete:

```sh
uv run cmake --build --preset dev --target tidy            # clang-tidy, about 1 minute here
uv run cmake --build --preset dev --target check_headers   # each header compiles alone
```

✅ Both finish without an error. [development.md](development.md#before-you-push) says what each catches.

## When something goes wrong

- **`uv: command not found`** after installing it: the shell was started before the installer changed its start-up files. Open a new terminal, or `source ~/.local/bin/env`.
- **CMake cannot find a C++ compiler**: the compiler from step 1 is missing. On Ubuntu, `build-essential`; on a Mac, `xcode-select --install`.
- **A test fails after a `git pull` that changed `cmake/patches/`**: the build tree still holds the dependency patched the old way. Delete `build/dev/_deps/<dependency>-*` and configure again ([development.md](development.md#dependencies)).
- **QBox's build stops at a missing header or `pkg-config` package**: one of QBox's packages from step 1 is missing. The log is in the terminal; the package is usually the header's name with `-dev` on the end.
