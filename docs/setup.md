# Setting up a machine for development

This page takes a fresh machine to one that builds socpuppet, passes every test, builds the firmware the tests boot, and (if you want it) has QBox built and ready. It was last walked through from a bare Ubuntu 26.04 install, and every timing below comes from that run, on a 24-core Intel machine (a Core Ultra 9 285K).

🧦 Once it is done, [Building and testing](development.md) is the everyday page.

## What gets installed, and by whom

```text
  apt / Homebrew  ──▶  the C++ compiler, git, zlib, dtc,           (root, once)
                       libuuid and iasl for EDK2
                       QBox's build packages, if you want QBox
  uv              ──▶  Python 3.13, CMake, Ninja, pytest,          (your home, no root)
                       clang-format, clang-tidy, ruff, the linters
  cmake --preset  ──▶  SystemC, SCC, DBT-RISE, Boost and friends   (build/dev/_deps)
  firmware/build.py ─▶  the Zephyr SDK, Zephyr, Zephyr's Python,    (build/firmware)
                       OpenSBI, EDK2
  tools/build_qbox.py ▶ QBox and its QEMU                          (build/qbox)
  Docker Desktop  ──▶  the devcontainer's image: the firmware      (Docker's own disk)
                       on an Intel Mac, and QBox for Linux, if wanted
```

💡 Only the first row needs root. Everything else lives in your home directory or in the checkout, so deleting `build/` takes the machine back to where it started.

💡 **clang-format and clang-tidy come from uv, not from apt or Homebrew.** `pyproject.toml` pins them as Python wheels (`uv sync` installs them), so that every machine and CI format and check the code with exactly the same versions. A clang-format of another version formats some lines differently, and the lint check would fail on code that looks right to you. You do not need a system clang at all: the build uses GCC on Linux and Apple clang on a Mac.

## 1. System packages

### Ubuntu (24.04 or 26.04)

```sh
sudo apt-get update && sudo apt-get install -y \
  build-essential git curl xz-utils zlib1g-dev device-tree-compiler uuid-dev acpica-tools gdb
```

| Package | Why |
|---|---|
| `build-essential` | GCC and make. socpuppet needs C++20, which GCC 13 (24.04) and GCC 15 (26.04) both have |
| `git`, `curl`, `xz-utils` | fetching the dependencies at configure time, and the Zephyr SDK |
| `zlib1g-dev` | SCC's FST trace writer, which waveform viewers such as GTKWave open, needs it |
| `device-tree-compiler` | `dtc`, which checks the devicetrees socpuppet generates and compiles the one OpenSBI is handed. The tests that need it skip without it |
| `uuid-dev`, `acpica-tools` | libuuid's header, which EDK2's `BaseTools` are built with, and `iasl`, which compiles EDK2's ACPI tables, both for `firmware/build.py` |
| `gdb` | debugging the simulator. The firmware's own GDB comes with the Zephyr SDK |

For QBox (step 5), add its build packages now, while you have `sudo` to hand. They are the ones the devcontainer's image has for it (`.devcontainer/Dockerfile`):

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
brew install dtc acpica
```

For QBox (step 5), add its Homebrew packages, which are QBox's own list without the LLVM that only its tests use:

```sh
brew install asio glib jpeg-turbo libelf libslirp libzip meson ninja pixman pkgconf sdl2
```

⚠️ On an Intel Mac, `firmware/build.py` needs [Docker Desktop](https://www.docker.com/products/docker-desktop/), because the Zephyr SDK has no toolchain for one. [development.md](development.md#firmware) has the details. QBox builds natively on a Mac with the packages above, and it can be built in the devcontainer's image instead, with Docker Desktop (step 5).

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
uv run firmware/build.py                 # about 6 minutes the first time
```

The first run downloads the Zephyr SDK's RISC-V toolchain and its LLVM, OpenSBI, EDK2 with its submodules, Zephyr itself, and a Python for Zephyr's and EDK2's build scripts into `build/firmware` (about 4 GB on disk, half of it EDK2's sources and build), then builds every image the tests boot. Later runs take a minute or two, most of it EDK2's.

Now run the suite as CI does, where a missing image is a failure and not a skip:

```sh
SOCPUPPET_REQUIRE_FIRMWARE=1 uv run ctest --preset dev
```

✅ You should see `100% tests passed`, with nothing skipped.

## 5. QBox (optional)

🎓 [QBox](https://github.com/qualcomm/qbox) is Qualcomm's library for putting QEMU's CPUs inside a SystemC simulation. QEMU translates the guest's instructions into the host's instead of interpreting them, which makes it many times faster than socpuppet's default CPU. socpuppet has it as a second hart, the `qbox_cpu` ([models/qbox-cpu.md](models/qbox-cpu.md)), for telling a bug in a hart from a bug in the firmware.

⚠️ QEMU is GPL-2.0. QBox is always built from source beside socpuppet and never goes into the wheel.

On Linux or a Mac, with the packages from step 1:

```sh
uv run tools/build_qbox.py            # QBox and its QEMU, into build/qbox/install: about 5 to 10 minutes
uv run cmake --preset qbox            # socpuppet linked with it, in build/qbox-dev
uv run cmake --build --preset qbox
SOCPUPPET_REQUIRE_FIRMWARE=1 uv run ctest --preset qbox
```

💡 `uv run` is there to put uv's CMake on the path for the tool. QBox's tree is about 3 GB, in `build/qbox`. The `qbox` test preset runs everything with the hart's tests on QBox's CPU (`SOCPUPPET_CPU=qbox_cpu`).

✅ You should see `100% tests passed`, with QBox's fates among the skipped, each saying why: what QBox's CPU does differently ([models/qbox-cpu.md](models/qbox-cpu.md)).

⚠️ The Python extension is copied into `python/socpuppet/` by whichever tree built last, so after building `qbox` the Python tests run against QBox's build until `dev` is built again.

💡 The native build on a Mac takes four patches of socpuppet's to QBox and QEMU ([upstream.md](upstream.md)), and it works on both kinds. On an Apple silicon MacBook Air (M4, macOS 26) QBox took 5½ minutes, socpuppet 2 and the suite 1; on an Intel 2019 Mac Pro, 9 minutes for QBox and 4 for the suite. CI builds it natively on an Apple silicon runner too.

On a Mac the same four commands can also run in the devcontainer's image, which is Linux with GCC, as CI builds, and has QBox's packages already. `tools/devcontainer.py` goes in front of each:

```sh
tools/devcontainer.py uv run tools/build_qbox.py     # about 7 minutes on an M4 Air, 10 on a 2019 Mac Pro
tools/devcontainer.py uv run cmake --preset qbox
tools/devcontainer.py uv run cmake --build --preset qbox
SOCPUPPET_REQUIRE_FIRMWARE=1 tools/devcontainer.py uv run ctest --preset qbox
```

💡 What these build is socpuppet and QBox for Linux, run in a container on the Mac. The tool builds the image the first time and keeps QBox's two trees on Docker volumes (`socpuppet-qbox` and `socpuppet-qbox-dev`), because a compiler reading the Mac's files through Docker is ten times slower. In the container the volumes sit where `build/qbox` and `build/qbox-dev` are, in front of whatever the Mac has there, so a native build and this one do not disturb each other. `docker volume rm socpuppet-qbox socpuppet-qbox-dev` is how to start this one again. The Linux extension it builds sits in `python/socpuppet/` beside the Mac's, under a name of its own, so neither build disturbs the other. [development.md](development.md#qbox-the-second-hart) says more.

## 6. Before your first push

CI runs two checks that `ctest` does not. Run them once now to be sure the toolchain is complete:

```sh
uv run cmake --build --preset dev --target tidy            # clang-tidy, about 1 minute here
uv run cmake --build --preset dev --target check_headers   # each header compiles alone
```

✅ Both finish without an error. [development.md](development.md#before-you-push) says what each catches.

To run every one of CI's jobs here before a push, the way CI runs them, there is one command. It takes the better part of an hour the first time, and says how far it has got as it goes ([development.md](development.md#running-cis-jobs-here)):

```sh
uv run python tools/ci.py               # add --docker for the wheels and the devcontainer
```

## When something goes wrong

- **`uv: command not found`** after installing it: the shell was started before the installer changed its start-up files. Open a new terminal, or `source ~/.local/bin/env`.
- **CMake cannot find a C++ compiler**: the compiler from step 1 is missing. On Ubuntu, `build-essential`; on a Mac, `xcode-select --install`.
- **A test fails after a `git pull` that changed `cmake/patches/`**: the build tree still holds the dependency patched the old way. Delete `build/dev/_deps/<dependency>-*` and configure again ([development.md](development.md#dependencies)).
- **QBox's build stops at a missing header or `pkg-config` package**: one of QBox's packages from step 1 is missing. `tools/build_qbox.py` checks for most of them before it starts, and names what is missing for apt and for Homebrew. Past that the log is in the terminal, and on Ubuntu the package is usually the header's name with `-dev` on the end.
