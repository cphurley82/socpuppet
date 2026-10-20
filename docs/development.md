# Building and testing socpuppet

## What you need

A C++20 compiler, [uv](https://docs.astral.sh/uv/), git, and a few system packages. [Setting up a machine for development](setup.md) lists them for Ubuntu and macOS and goes from a bare install to every test passing, QBox included; or open the repo in the devcontainer (`.devcontainer/`), which is the CI environment. Ubuntu 24.04 and macOS are both supported and both run in CI.

## The loop

```sh
uv sync                                  # tools: Python, cmake, ninja, pytest, the linters
uv run cmake --preset dev                # configure (fetches the dependencies the first time)
uv run cmake --build --preset dev        # format, then build
uv run ctest --preset dev                # every test: C++, Python, lint (eight at a time)
```

⚠️ The first build takes several minutes: SystemC, SCC and the parts of Boost that SCC needs are compiled from source. After that, builds are incremental.

💡 Building formats the C++ and Python for you and treats compiler warnings in our code as errors, and `ctest` includes a lint check over the whole tree. [Style, and the tools that hold us to it](style.md) says what the rules are and why.

The build puts the Python extension next to the Python sources, so the package runs straight from the tree:

```sh
uv run pytest                            # just the Python tests
uv run pytest -n auto --dist loadscope --no-loadscope-reorder   # the same, on every core
PYTHONPATH=python uv run python examples/m0_passthrough.py
```

💡 `ctest` runs the Python tests on every core with [pytest-xdist](https://pytest-xdist.readthedocs.io), which takes about a minute where one core takes six. `--dist loadscope` keeps the tests of one class on one worker, so a board the class shares is built once. The boots of OpenSBI and UEFI take most of a minute each, so they are marked `@pytest.mark.long` and handed out first: started last, one would keep the whole run waiting while every other core sat idle. `--no-loadscope-reorder` stops xdist from putting the classes with the most tests first instead.

## The tests

| Where | What | Runs |
|---|---|---|
| `tests/cpp/unit/` | plain C++ logic, no simulator | all in one process |
| `tests/cpp/contracts/` | contract suites every implementation of a slot must pass | one process per test |
| `tests/cpp/platform/` | composed platforms | one process per test |
| `tests/python/` | the Python API | `@pytest.mark.platform` tests get a process each |
| `tests/tooling/` | the lint runner and the build-time checks | each makes a throwaway repository or CMake project |
| `python/socpuppet/zephyr_module/tests/`, `firmware/**/testcase.yaml` | ztest suites and applications that run inside Zephyr, on a board | by twister, with `firmware/twister.py`. Not part of `ctest` |
| Zephyr's own `tests/` and `samples/` | the board-compliance run: Zephyr's suites on every board | by twister, with `uv run firmware/twister.py --suites`, and in CI's `twister` job |

💡 "One process per test" is because the SystemC kernel cannot be restarted. Run the C++ kernel tests through `ctest`, not by launching the test binary by hand: launched directly, the second test in the binary would find the kernel already used.

## Coverage

How much of our own code do the tests run?

```sh
uv run cmake --preset coverage
uv run cmake --build --preset coverage --target coverage
```

That builds our code with counters in it, runs the tests, and prints two tables: one for the C++ under `src/` and one for the Python under `python/`. The line-by-line reports are web pages in `build/dev/coverage/`. The target fails if either figure drops below its floor, which is set in `CMakePresets.json`. CI runs it and keeps the reports as an artifact of the run.

💡 Coverage counts lines of code the compiler produced. An inline or template function that nothing calls produces no code, so it is missing from the C++ report, where you might expect to see it at 0%. A file that is absent from the table has not been tested at all.

## Sanitizers

The C++ tests can be built so that a mistake which usually goes unnoticed stops the program instead: reading past the end of an allocation, using memory after freeing it, overflowing a signed integer, indexing past the end of a vector.

```sh
uv run cmake --preset asan
uv run cmake --build --preset asan
uv run ctest --preset asan
```

🎓 The tools are AddressSanitizer and UndefinedBehaviorSanitizer, which the compiler builds into the test programs. On Linux they also report memory that was never freed. Only our two C++ test programs are built this way. The Python extension is not, because Python itself is not, and a sanitized module cannot be loaded into a program that is not sanitized.

## Before you push

⚠️ CI checks three things that the loop above does not, and each has turned a push red that passed every test here:

```sh
uv run cmake --build --preset dev --target tidy            # clang-tidy, a few minutes
uv run cmake --build --preset dev --target check_headers   # each header compiles alone
```

- **clang-tidy**, with its warnings as errors. It reads the same code the compiler did and finds what a compiler lets through: arithmetic that mixes `*` and `+` with no brackets, a multiplication done in 32 bits and then widened, a constant at namespace scope whose constructor could throw.
- **The header check**, which compiles each of our headers on its own, so that one that leans on what another file happened to include is found.
- **GCC, on Linux.** On a Mac the compiler is Apple's clang, and GCC has warnings it lacks. To have them here, keep a second build tree in the devcontainer's image, which is what CI builds in. The first build is long and later ones are incremental:

```sh
tools/devcontainer.py uv run cmake --preset linux        # build/linux, the dev preset's configuration
tools/devcontainer.py uv run cmake --build --preset linux
tools/devcontainer.py uv run ctest --preset linux
```

💡 `tools/devcontainer.py` runs any command in the devcontainer's image, with the repository at `/workspace` (`tools/devcontainer.py bash` is a shell there). It names the image after a hash of `.devcontainer/Dockerfile`, so it builds the image the first time and again whenever the Dockerfile changes. uv's Linux venv, its cache and its Python are kept in `build/`, so they outlive each container, and your `SOCPUPPET_*` variables go in with the command. 🎓 The container is a Linux machine of its own, with its own compiler, so what it builds for itself is kept apart from the host's own, even on a Linux host: QBox's two trees, its firmware tools in `build/firmware/linux-<processor>`, and twister's folder. On a Mac each is a Docker volume (`socpuppet-qbox`, `socpuppet-qbox-dev`, `socpuppet-firmware-linux`, `socpuppet-twister`), which a compiler reads ten times faster than the Mac's own files, and on Linux a folder of `build/container`. Each sits where the container looks, in front of the host's own. ⚠️ A second build tree has its own copy of every dependency, patched when it was fetched. After a change to a file in `cmake/patches/`, that tree's copy is stale too: delete it and configure again, as [Dependencies](#dependencies) says. `firmware/twister.py` keeps the same tree, `build/linux`, on an Intel Mac, and does that by itself.

## Running CI's jobs here

`tools/ci.py` holds the steps of every job CI runs, and CI's workflow, `.github/workflows/ci.yml`, is a thin wrapper around it: each of its jobs checks out the code, installs packages, restores caches, and then runs `uv run python tools/ci.py run JOB`. So the same command runs every job on this machine, and a push is not the first time they run:

```sh
uv run python tools/ci.py                 # every job that can run here, three at a time
uv run python tools/ci.py --docker        # the jobs in Docker too: the wheels, the devcontainer
uv run python tools/ci.py lint tidy test  # just those
uv run python tools/ci.py -j 1 --clean    # one at a time, the patched dependencies dropped first
uv run python tools/ci.py --list          # the jobs, what each needs, and why one is skipped here
```

🩺 A run starts by asking `tools/doctor.py` whether this machine has what the jobs need: socpuppet's build tools, the firmware's, QBox's packages, the network, Docker. A job that needs something missing fails straight away, before any job starts, and the problem and the command that fixes it are printed at the top. A job that needs only something optional, QBox's packages or Docker, is skipped instead, saying what is missing. `uv run python tools/doctor.py` runs the same check on its own.

🧦 A run says where it has got to on every line: each job's start, pass, failure or skip ends with a tally of how many have passed, failed, been skipped, are running and are waiting. A job starts once the jobs it needs have passed, and the quick ones go first, so `lint` has answered within a minute. A step that fails ends its job, and the jobs that need it are skipped and say why; the rest carry on. The step's output is in `build/ci/<job>-<step>.log`, and its last fifteen lines are printed where it failed. Ctrl-C stops every step that is running. The summary at the end says how long the whole run took.

- **A red job in CI says how to run it here.** Its log opens with the command, such as `uv run python tools/ci.py firmware test`, which names the jobs it needs before it.
- **A job named without the jobs it needs** takes what they make as made already: `tools/ci.py test` uses the firmware already in `build/firmware`.
- **Some jobs are skipped, with the reason.** `wheel` (on Linux, where cibuildwheel builds in a container) and `devcontainer` run in Docker, so they need `--docker` or their own name, Docker installed, and `docker info` answering, which means being in the `docker` group. The doctor says which of those is missing. `devcontainer` runs only when this branch has changed `.devcontainer/`, as CI's does. `tidy` and `qbox-tidy` are Linux's, since clang-tidy reads GCC's compile commands.
- 💡 **Jobs that build into the same tree take turns.** `test`, `twister`, `coverage` and `sanitizers` all write the extension into `python/socpuppet/`, whichever tree they build, so at most one of them runs at once, and `-j` cannot change that. After `coverage` or `sanitizers`, the run configures `build/dev` for `dev` again.
- 🎓 This is your machine and not CI's runner, so it runs your compiler and your libraries. A difference between the two, such as a newer GCC with a warning CI's lacks, shows up here as a failure, which is the point. The QBox jobs need the packages [setup.md](setup.md#1-system-packages) lists for QBox, and `qbox-build` takes the better part of ten minutes the first time.

⚠️ A build tree whose dependencies were patched by an older set of patches fails to configure with `patch does not apply`, because `git apply` does not apply a patch twice ([Dependencies](#dependencies)). The runner keeps a hash of `cmake/patches/`, `cmake/Dependencies.cmake` and `tools/build_qbox.py` in each tree, `_deps/.socpuppet-patches` in `build/dev`, `build/qbox-dev`, `build/linux` and QBox's own tree. When a tree's is not the patches' hash, or it has none, the runner deletes that tree's patched dependencies, QBox's rpclib in its tree, so that they are fetched and patched again. Everything not patched is kept, libqemu included. 💡 Each tree has a record of its own because the container keeps its own trees where QBox's are, apart from the host's: a run there sees only its own. A tree deleted and configured afresh between two runs has no record, so the next run fetches its patched dependencies once more.

## One build tree, three kinds of build

⚠️ The `dev`, `coverage` and `asan` presets share `build/dev`, so that SystemC and the other dependencies are compiled only once. The tree holds whichever kind was configured last, and `cmake --build` does not change that. After a coverage or sanitizer run, go back with:

```sh
uv run cmake --preset dev
```

Configuring prints a note when the tree is in one of the two special modes.

## QBox, the second hart

🎓 The `qbox_cpu` is QEMU's RISC-V CPU inside SystemC, by way of Qualcomm's QBox, beside the DBT-RISE CPU ([models/qbox-cpu.md](models/qbox-cpu.md)). QEMU is GPL-2.0, so it is built from source by whoever wants it, and it has a tree of its own:

```sh
uv run tools/build_qbox.py               # QBox at its pin, with cmake/patches/qbox-* and libqemu-*, into build/qbox/install
uv run cmake --preset qbox               # build/qbox-dev, with SOCPUPPET_QBOX_DIR=build/qbox/install
uv run cmake --build --preset qbox
uv run ctest --preset qbox               # the whole suite, with SOCPUPPET_CPU=qbox_cpu
```

- **`SOCPUPPET_QBOX_DIR`** names a QBox install. With it, socpuppet links QBox's shared SystemC and CCI, since a program holds one SystemC kernel, and builds the adapter. Without it, SystemC is fetched at the commit QBox builds and linked statically, as always.
- **`SOCPUPPET_CPU`**, `dbt_rise_cpu` or `qbox_cpu`, is the CPU the hart's C++ tests run on (`tests/cpp/support/the_cpu.h`), and the host's CPU wherever a Python program does not name one (`host(cpu=)`), which is how the `qbox` test preset runs the host boots and how twister's runs follow it.
- **The fates.** What QBox's CPU does differently is skipped on QBox with the reason: the hart's C++ cases are in one table (`tests/cpp/support/qbox_fates.h`), and a Python test has `@pytest.mark.not_on_qbox(reason)`. A failure that is in neither is new.
- 💡 CI does all of this on every push, on Linux and natively on an Apple silicon Mac, with twister on the host board on both and clang-tidy over the adapter on Linux: the `qbox-build`, `qbox` and `qbox-tidy` jobs, which `uv run python tools/ci.py qbox-build qbox qbox-tidy` runs here. ⚠️ On an Intel Mac, where twister runs in a Linux container with a socpuppet that has no QBox in it, that run of `qbox` stops after its tests. QBox itself is built only when its pin or its patches change, and cached.
- ⚠️ The extension in `python/socpuppet/` is the last tree's to be built, as for any second tree.
- ⚠️ A change to a QBox patch is not applied to a QBox that is already built: `tools/build_qbox.py` applies a patch once. Delete `build/qbox` and run it again.
- **On a Mac** the four commands work natively, with Homebrew's packages and four patches of ours to QBox and QEMU, or in the devcontainer's image with `tools/devcontainer.py` in front of each, which builds for Linux with GCC as CI does. [setup.md](setup.md#5-qbox-optional) has both, and why the container keeps QBox's trees on Docker volumes.

## Spikes

Sometimes the honest way to answer a design question is to try it. Code written for that lives under `spikes/`, and it is deliberately held to different rules from the rest of the tree: it is not written test-first, nothing in `src/`, `python/` or `tests/` may depend on it, and it is deleted once the question is answered. It is still linted.

One spike is in the build today, behind an option that is off by default. The NPU spike ([spikes/npu](../spikes/npu/README.md), report in [npu-spike.md](history/npu-spike.md)) asks what should sit in the accelerator slot. `SOCPUPPET_BUILD_SPIKES` turns it on, and the `spike` preset is the `dev` preset with that set, so that the everyday build, coverage and the wheel never see it:

```sh
uv sync --group spike                  # what the spike needs beyond the dev tools (numpy)
uv run cmake --preset spike
uv run cmake --build --preset spike
uv run ctest --preset spike            # only the tests labelled `spike`
```

The speed spike ([spikes/speed](../spikes/speed/README.md), report in [speed-spike.md](history/speed-spike.md)) is behind the same option and stays, unlike the others, so that every later change to the core can be timed against its results. `uv run ctest --preset speed` runs its three loops one at a time, verbosely, and `spikes/speed/run.sh` does one machine's whole column into `spikes/speed/results/`.

The earlier spikes have gone, each when the milestone it served had rebuilt what it found test-first, and each report names the last commit that held its code. [history/README.md](history/README.md) lists them, with the question each answered.

## Firmware

Some tests boot real firmware: Zephyr samples and applications of ours, built with the Zephyr SDK; the boot ROM in `firmware/rom`, which is bare-metal C built with the SDK's compiler and no Zephyr; OpenSBI v1.9, for the host, with its `test_payload`; `firmware/sbi_payload`, a payload of ours for OpenSBI, built as the ROM is; EDK2 `edk2-stable202608`, which is UEFI, built from its port for QEMU's RISC-V `virt` as `uefi.fd`, to run where OpenSBI jumps; and 🐧 Linux 6.18, a stock `defconfig` kernel for the host, as `linux.bin`, with its symbols in `linux.elf`, and its root filesystem, Alpine's mini root with an inittab of ours in it (`firmware/rootfs`, a tree shaped as the guest's), as `rootfs.ext4`.

```sh
uv run firmware/build.py              # everything, into build/firmware
uv run firmware/build.py rom zephyr   # just those parts, and what they need
```

The parts are `sdk`, `llvm` and `zephyr-tree`, which fetch what the rest is built with, and `rom`, `opensbi`, `zephyr`, `edk2` and `linux`, which build the images. Each fetches what it needs first, so naming one is enough, and `-j N` builds that many of Zephyr's images at once. CI builds the five kinds of image in five jobs side by side, each cached on what it is built from (`uv run python tools/ci.py --list` shows them).

- The script downloads the SDK's RISC-V toolchain (about 225 MB), the SDK's LLVM (about 260 MB, two gigabytes unpacked), OpenSBI, EDK2 with its submodules, Zephyr 4.4.2, the kernel's release tarball (about 150 MB) and Alpine's mini root filesystem (3 MB), each checked against the SHA-256 pinned in `firmware/versions.toml`, and a Python for Zephyr's and EDK2's build scripts into `build/firmware` the first time, which takes a few minutes. After that it takes a minute or two, most of it EDK2's. The kernel's build takes a few minutes on its own, on every core the machine has. OpenSBI, EDK2 and Zephyr are cloned at the tag pinned there, one commit deep, and a tree at another tag, after its pin changes, is removed and cloned afresh.
- ⚠️ **The kernel builds in Docker on a Mac**, whatever the chip, as every part does on an Intel Mac: the kernel's tree has files whose names differ only in their case, which a Mac's file system keeps as one, and its build wants a newer GNU make than a Mac has. `firmware/build.py linux` does this by itself; the other parts build natively on an Apple-silicon Mac as before.
- 💡 **What runs on the machine, and what its tools build, is kept in a folder named for it**, `build/firmware/<machine>` (`linux-x86_64`, `macos-aarch64`): the SDK, its LLVM, Zephyr's Python and venv, the kernel's tree, which a Mac's file system cannot hold, and EDK2's, whose build compiles this machine's tools inside it, and the build folder of each part, `build_opensbi`, `build_edk2`, `build_linux` and one `build_<image>` for each of Zephyr's images. The images, the build logs, Zephyr's and OpenSBI's trees and the rest are in `build/firmware` itself. Docker's container, where the kernel builds on a Mac, is a machine of its own, and its folder is kept apart from the host's: on a Mac it is the Docker volume `socpuppet-firmware-linux`, which a Mac's file system does not get to fold the case of the kernel's file names in, and which `docker volume rm socpuppet-firmware-linux` throws away; on Linux it is `build/container/firmware-linux`. The SDK, LLVM, `venv` and `python` folders an older build left in `build/firmware` itself, and its `linux`, `edk2` and `build_*` folders, can be deleted.
- 🎓 **OpenSBI is built with the SDK's LLVM and not its GCC.** OpenSBI runs wherever it is put, by being linked as a position-independent executable, and the SDK's GNU linker is built for bare-metal programs and cannot make one. LLVM's can, for any target. It is kept beside the SDK and not in it, so that what copies or caches the SDK for Zephyr does not carry it.
- 🎓 **So is EDK2**, whose build links every module with `-z notext`, which the SDK's GNU linker refuses. Its `BaseTools` are built with the machine's own compiler, which is why it needs libuuid's headers, and a driver or two have ACPI tables that `iasl` compiles. The script says so and stops when there is no `iasl`.
- 📮 **OpenSBI's and EDK2's patches** are `cmake/patches/opensbi-*.patch` and `cmake/patches/edk2-*.patch`, each with its entry in [upstream.md](upstream.md), and the script applies them to a clean tree every time, so that a patch that changes is the one built.
- 💡 On an Apple silicon Mac the script runs on macOS itself: the SDK has a toolchain for one, and nothing else has to be installed but `iasl`. Every image builds in a minute there. ⚠️ EDK2's part of it has been run on Linux only so far: CI builds it there, and nothing builds it on a Mac yet.
- 💡 On an Intel Mac the same command works, and it needs Docker. The Zephyr SDK ships no macOS x86-64 toolchain, so there the script runs itself in the devcontainer's image, which is Linux and has one, by way of `tools/devcontainer.py`, which builds the image the first time and again when `.devcontainer/Dockerfile` changes. `--in-docker` does the same on any machine. The images it leaves in `build/firmware` are plain RISC-V ELF files, so the tests on the Mac boot them as they are. Each run takes a few minutes there, not seconds: the files are the Mac's, and a container reaches them slowly.
- ⚠️ The toolchain an Intel Mac ends up with is Linux's, GDB included, in the `socpuppet-firmware-linux` volume. To debug from there, run GDB in the same image ([boot-your-firmware.md](boot-your-firmware.md#debugging-with-gdb) has the command).
- A test that needs an image you have not built is skipped, and says so. Set `SOCPUPPET_REQUIRE_FIRMWARE=1` to make it fail instead, which is what CI does.
- A test marked `@pytest.mark.on_demand("why")` is worth running but too long to run every time, such as 🐧 Linux booted through UEFI from the flash. It is skipped unless `SOCPUPPET_ON_DEMAND=1`, and the skip says so: `SOCPUPPET_ON_DEMAND=1 uv run pytest tests/python/test_m20_exit.py`.
- `SOCPUPPET_FIRMWARE_DIR` points the tests at images kept somewhere else.

`firmware/twister.py` is the other thing to run there. It has twister, Zephyr's test runner, build Zephyr's own test suites and ours for each board and run every one on socpuppet, which is how a change to a model, a driver or a board is held to several thousand tests nobody here wrote. It takes six and a half minutes for the whole list on an Apple silicon Mac and about eight on an Intel one, where it runs in Docker, so it is for before a push and for CI, and not for the inner loop. [twister.md](twister.md) is its page.

```sh
uv run firmware/twister.py --suites                                   # everything, on every board
uv run firmware/twister.py -T python/socpuppet/zephyr_module/tests    # the drivers' own tests
```

## The package

```sh
uv build --wheel
uv run python tools/check_wheel.py dist/*.whl     # contents are what they should be
tools/test_wheel.py uv dist/*.whl                 # install in a clean env, run the tests there
tools/test_wheel.py pip dist/*.whl
```

The wheel is self-contained: SystemC, SCC and their dependencies are linked statically into the one extension module.

That wheel is for your own machine. The ones a user will install are built in CI by [cibuildwheel](https://cibuildwheel.pypa.io), as configured under `[tool.cibuildwheel]` in `pyproject.toml`: one per Python version, for Linux on Intel and Arm and for macOS on Apple silicon. 🎓 A Linux wheel has to run on many distributions, so it is built inside a deliberately old one (a "manylinux" container) and then checked to depend on nothing a distribution might lack. To try the build locally, which on Linux needs Docker:

```sh
uv run python tools/ci.py wheel     # this machine's wheel, for the pinned Python, into build/wheelhouse
```

- 💡 It builds from a source distribution and not from the checkout, because cibuildwheel copies the whole directory it is given into its container, and `build/` is far too big to copy.
- On Linux the container's compiler cache is kept in `build/ccache`, so the second build takes the dependencies from the first. The container runs as root, so the cache is left for anyone on the machine to write to and remove.
- cibuildwheel's own test of the wheel is skipped here, since the job then installs the same wheel with uv and with pip and tests it with the firmware. In CI it tests every wheel.
- The macOS wheels need macOS 13.3 or newer. The code uses C++20's `std::format` for floating-point numbers, which the system's C++ library has had since that release.
- 🚧 Nothing is published yet. CI keeps the wheels as artifacts of each run.

## How changes are made

Test-first, following `.claude/skills/tdd`: state the behavior as "in scenario X, Y happens", write one test for it, watch it fail, then write just enough code. Tests are named for the scenario and the outcome, and drive real blocks through their public interfaces.

## Dependencies

Pinned in `cmake/Dependencies.cmake` and fetched at configure time. Third-party licenses are listed in `THIRD_PARTY_NOTICES.md`.

The register maps in `regs/` are compiled by [systemrdl-compiler](https://github.com/SystemRDL/systemrdl-compiler) (MIT), which `uv sync` installs with the linters. It is a developer's tool and not a dependency of the package: what `tools/regs.py` generates with it is checked in, so a build needs only a compiler and an installed socpuppet has no use for it. ⚠️ After changing a `.rdl`, run `uv run python tools/lint.py --fix`, and then `firmware/build.py`, because the firmware images are built from the generated headers too.

SCC needed a few accommodations to build inside this tree, each commented where it is made: two small patches (`cmake/patches/`), one to a configure-time probe and one so that clang-tidy can read the CCI headers it bundles, its install rules switched off, our SystemC declared as already found, and Boost.Filesystem linked explicitly.

QBox, the second CPU, is not fetched at all: `tools/build_qbox.py` builds it at its pin, applying `cmake/patches/qbox-*.patch` to it and `libqemu-*.patch` to the QEMU it fetches ([QBox, the second hart](#qbox-the-second-hart)).

DBT-RISE-RISCV, the CPU model, is built by its own CMake as a static library, with the patches named `dbt-rise-*` in `cmake/patches/`, to it and to the core library under it, and a few accommodations of the same kind. ⚠️ `git apply` does not apply a patch twice. When a patch file changes, or a build tree still holds a dependency patched the old way, delete `build/<tree>/_deps/<dependency>-*` and configure again.

🎓 **Making a patch when others are stacked on the same file.** The patches of one project are applied in the order `cmake/Dependencies.cmake` lists them, each to what the ones before it left, so a new one is a diff against exactly that. Work in a build tree's copy (`build/dev/_deps/<dependency>-src`), which is a git checkout with every patch applied and nothing committed. To get the diff of yours alone, put the earlier patches in that checkout's index and compare the working tree with it: `git reset -q`, then `git apply --cached` each earlier patch in order, then `git diff > cmake/patches/<project>-<what>.patch`. ⚠️ Three things go wrong otherwise. A diff against the checkout's `HEAD` has every earlier patch in it. An index that still holds a draft of your own patch gives you only what changed since the draft. And to change a patch that has later ones stacked on it, take those out of the working tree first (`git apply -R`, last one first) and put them back afterwards. Then delete the dependency from the build tree and configure again, so that the whole list is applied from scratch, which is the test that it can be.

📮 A change to someone else's code is a `git apply` file in `cmake/patches/`, and the same commit adds an entry to [upstream.md](upstream.md) saying what is wrong, how to see it and what to propose. That page is the list to work from when the fixes are sent upstream.
