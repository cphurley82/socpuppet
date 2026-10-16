# Building and testing socpuppet

## What you need

💡 Setting up a machine for the first time? [Setting up a machine for development](setup.md) goes from a bare install to every test passing, QBox included, step by step.

- A C++20 compiler: GCC 13 or newer, or a recent Clang (Apple clang works).
- [uv](https://docs.astral.sh/uv/). It supplies Python, CMake and Ninja, so none of those need installing.
- git, and zlib's headers (`zlib1g-dev` on Ubuntu; already there on macOS).
- `dtc`, the devicetree compiler (`device-tree-compiler` on Ubuntu, `brew install dtc` on macOS). Two Python tests that check generated devicetrees skip without it.
- For `firmware/build.py`, which builds EDK2: libuuid's headers (`uuid-dev` on Ubuntu; already there on macOS) and `iasl`, ACPICA's compiler (`acpica-tools` on Ubuntu, `brew install acpica` on macOS).

Ubuntu 24.04 and macOS are both supported and both run in CI. Ubuntu 26.04 (GCC 15) is not in CI, and every job's steps have been run on it and pass: [Running CI's jobs here](#running-cis-jobs-here) is how to check that again. If you would rather not set anything up, open the repo in the devcontainer (`.devcontainer/`), which is the CI environment.

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
PYTHONPATH=python uv run python examples/m0_passthrough.py
```

## The tests

| Where | What | Runs |
|---|---|---|
| `tests/cpp/unit/` | plain C++ logic, no simulator | all in one process |
| `tests/cpp/contracts/` | contract suites every implementation of a slot must pass | one process per test |
| `tests/cpp/platform/` | composed platforms | one process per test |
| `tests/python/` | the Python API | `@pytest.mark.platform` tests get a process each |
| `tests/tooling/` | the lint runner and the build-time checks | each makes a throwaway repository or CMake project |
| `python/socpuppet/zephyr_module/tests/`, `firmware/**/testcase.yaml` | ztest suites and applications that run inside Zephyr, on a board | by twister, with `firmware/twister.sh`. Not part of `ctest` |
| Zephyr's own `tests/` and `samples/` | the board-compliance run: Zephyr's suites on every board | by twister, with `firmware/twister.sh --suites`, and in CI's `twister` job |

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
tools/devcontainer.sh uv run cmake --preset linux        # build/linux, the dev preset's configuration
tools/devcontainer.sh uv run cmake --build --preset linux
tools/devcontainer.sh uv run ctest --preset linux
```

💡 `tools/devcontainer.sh` runs any command in the devcontainer's image, with the repository at `/workspace` (`tools/devcontainer.sh bash` is a shell there). It names the image after a hash of `.devcontainer/Dockerfile`, so it builds the image the first time and again whenever the Dockerfile changes. uv's Linux venv, its cache and its Python are kept in `build/`, so they outlive each container, and your `SOCPUPPET_*` variables go in with the command. ⚠️ A second build tree has its own copy of every dependency, patched when it was fetched. After a change to a file in `cmake/patches/`, that tree's copy is stale too: delete it and configure again, as [Dependencies](#dependencies) says. `firmware/twister.sh` keeps the same tree, `build/linux`, on an Intel Mac, and does that by itself.

## Running CI's jobs here

`tools/ci.py` holds the steps of every job CI runs, and CI's workflow, `.github/workflows/ci.yml`, is a thin wrapper around it: each of its jobs checks out the code, installs packages, restores caches, and then runs `uv run python tools/ci.py run JOB`. So the same command runs every job on this machine, and a push is not the first time they run:

```sh
uv run python tools/ci.py                 # every job that can run here, three at a time
uv run python tools/ci.py --docker        # the jobs in Docker too: the wheels, the devcontainer
uv run python tools/ci.py lint tidy test  # just those
uv run python tools/ci.py -j 1 --clean    # one at a time, the patched dependencies dropped first
uv run python tools/ci.py --list          # the jobs, what each needs, and why one is skipped here
```

🧦 A run says where it has got to on every line: each job's start, pass, failure or skip ends with a tally of how many have passed, failed, been skipped, are running and are waiting. A job starts once the jobs it needs have passed, and the quick ones go first, so `lint` has answered within a minute. A step that fails ends its job, and the jobs that need it are skipped and say why; the rest carry on. The step's output is in `build/ci/<job>-<step>.log`, and its last fifteen lines are printed where it failed. Ctrl-C stops every step that is running.

- **A red job in CI says how to run it here.** Its log opens with the command, such as `uv run python tools/ci.py firmware test`, which names the jobs it needs before it.
- **A job named without the jobs it needs** takes what they make as made already: `tools/ci.py test` uses the firmware already in `build/firmware`.
- **Some jobs are skipped, with the reason.** `wheel` (on Linux, where cibuildwheel builds in a container) and `devcontainer` run in Docker, so they need `--docker` or their own name, Docker installed, and `docker info` answering, which means being in the `docker` group. `devcontainer` runs only when this branch has changed `.devcontainer/`, as CI's does. `tidy` and `qbox-tidy` are Linux's, since clang-tidy reads GCC's compile commands.
- 💡 **Jobs that build into the same tree take turns.** `test`, `twister`, `coverage` and `sanitizers` all write the extension into `python/socpuppet/`, whichever tree they build, so at most one of them runs at once, and `-j` cannot change that. After `coverage` or `sanitizers`, the run configures `build/dev` for `dev` again.
- 🎓 This is your machine and not CI's runner, so it runs your compiler and your libraries. A difference between the two, such as a newer GCC with a warning CI's lacks, shows up here as a failure, which is the point. The QBox jobs need the packages [setup.md](setup.md#1-system-packages) lists for QBox, and `qbox-build` takes the better part of ten minutes the first time.

⚠️ A build tree whose dependencies were patched by an older set of patches fails to configure with `patch does not apply`, because `git apply` does not apply a patch twice ([Dependencies](#dependencies)). The runner keeps a hash of `cmake/patches/`, `cmake/Dependencies.cmake` and `tools/build_qbox.sh` in `build/ci/.patches`. When it has changed, or there is none, it deletes the patched dependencies in `build/dev`, `build/qbox-dev` and `build/linux`, and QBox's rpclib, so that they are fetched and patched again. Everything not patched is kept, libqemu included.

## One build tree, three kinds of build

⚠️ The `dev`, `coverage` and `asan` presets share `build/dev`, so that SystemC and the other dependencies are compiled only once. The tree holds whichever kind was configured last, and `cmake --build` does not change that. After a coverage or sanitizer run, go back with:

```sh
uv run cmake --preset dev
```

Configuring prints a note when the tree is in one of the two special modes.

## QBox, the second hart

🎓 The `qbox_cpu` is QEMU's RISC-V CPU inside SystemC, by way of Qualcomm's QBox, beside the DBT-RISE CPU ([models/qbox-cpu.md](models/qbox-cpu.md)). QEMU is GPL-2.0, so it is built from source by whoever wants it, and it has a tree of its own:

```sh
uv run tools/build_qbox.sh               # QBox at its pin, with cmake/patches/qbox-* and libqemu-*, into build/qbox/install
uv run cmake --preset qbox               # build/qbox-dev, with SOCPUPPET_QBOX_DIR=build/qbox/install
uv run cmake --build --preset qbox
uv run ctest --preset qbox               # the whole suite, with SOCPUPPET_CPU=qbox_cpu
```

- **`SOCPUPPET_QBOX_DIR`** names a QBox install. With it, socpuppet links QBox's shared SystemC and CCI, since a program holds one SystemC kernel, and builds the adapter. Without it, SystemC is fetched at the commit QBox builds and linked statically, as always.
- **`SOCPUPPET_CPU`**, `dbt_rise_cpu` or `qbox_cpu`, is the CPU the hart's C++ tests run on (`tests/cpp/support/the_cpu.h`), and the host's CPU wherever a Python program does not name one (`host(cpu=)`), which is how the `qbox` test preset runs the host boots and how twister's runs follow it.
- **The fates.** What QBox's CPU does differently is skipped on QBox with the reason: the hart's C++ cases are in one table (`tests/cpp/support/qbox_fates.h`), and a Python test has `@pytest.mark.not_on_qbox(reason)`. A failure that is in neither is new.
- 💡 CI does all of this on every push, on Linux and natively on an Apple silicon Mac, with twister on the host board on both and clang-tidy over the adapter on Linux: the `qbox-build`, `qbox` and `qbox-tidy` jobs, which `uv run python tools/ci.py qbox-build qbox qbox-tidy` runs here. QBox itself is built only when its pin or its patches change, and cached.
- ⚠️ The extension in `python/socpuppet/` is the last tree's to be built, as for any second tree.
- ⚠️ A change to a QBox patch is not applied to a QBox that is already built: `tools/build_qbox.sh` applies a patch once. Delete `build/qbox` and run it again.
- **On a Mac** the four commands work natively, with Homebrew's packages and four patches of ours to QBox and QEMU ([setup.md](setup.md#5-qbox-optional), [upstream.md](upstream.md)). They also work with `tools/devcontainer.sh` in front of each, which builds for Linux with GCC, as CI does. ⚠️ There `build/qbox` and `build/qbox-dev` are Docker volumes, `socpuppet-qbox` and `socpuppet-qbox-dev`, mounted where the preset looks for them, because a compiler reading through Docker's file sharing is ten times slower than one reading a volume ([twister-spike.md](twister-spike.md)). They stand in front of the Mac's own two directories, so a native build and the container's never meet. To start the container's over, `docker volume rm socpuppet-qbox socpuppet-qbox-dev` stands in for deleting them.

## Spikes

Sometimes the honest way to answer a design question is to try it. Code written for that lives under `spikes/`, and it is deliberately held to different rules from the rest of the tree: it is not written test-first, nothing in `src/`, `python/` or `tests/` may depend on it, and it is deleted once the question is answered. It is still linted.

One spike is in the build today, behind an option that is off by default. The NPU spike ([spikes/npu](../spikes/npu/README.md), report in [npu-spike.md](npu-spike.md)) asks what should sit in the accelerator slot. `SOCPUPPET_BUILD_SPIKES` turns it on, and the `spike` preset is the `dev` preset with that set, so that the everyday build, coverage and the wheel never see it:

```sh
uv sync --group spike                  # what the spike needs beyond the dev tools (numpy)
uv run cmake --preset spike
uv run cmake --build --preset spike
uv run ctest --preset spike            # only the tests labelled `spike`
```

The speed spike ([spikes/speed](../spikes/speed/README.md), report in [speed-spike.md](speed-spike.md)) is behind the same option and stays, unlike the others, so that every later change to the core can be timed against its results. `uv run ctest --preset speed` runs its three loops one at a time, verbosely, and `spikes/speed/run.sh` does one machine's whole column into `spikes/speed/results/`.

The earlier spikes have gone. The twister spike asked whether Zephyr's test runner could run Zephyr's own tests on socpuppet's boards ([twister-spike.md](twister-spike.md)). It was scripts and a few Zephyr files, and it was deleted when M21's steps had rebuilt what it found test-first, as `socpuppet run`, the boards' two files for twister and `firmware/twister.sh`; the report names the commit that holds it. The GDB spike asked whether each of three CPUs can have a debugger at once ([gdb-spike.md](gdb-spike.md)). It was two scripts and no C++, so it needed no option and no preset, and it was deleted when M8's step 4 had rebuilt what it found test-first; the report names the commit that holds it. The ISS spike answered its question (see [iss-spike.md](iss-spike.md)) and was cleared away when M3a finished. What is left of it, [spikes/iss](../spikes/iss/README.md), is the spike's own QBox integration; socpuppet's is the `qbox_cpu`, built by `tools/build_qbox.sh` (M27). The PCIe spike answered its question at M2 ([pcie-spike.md](pcie-spike.md)) and was deleted after; the report names the commit that holds it. The boot spike answered four questions ahead of M14 ([boot-spike.md](boot-spike.md)) and was deleted when that milestone's steps had rebuilt what it found test-first; the report names the commit that holds it.

## Firmware

Some tests boot real firmware: Zephyr samples and applications of ours, built with the Zephyr SDK; the boot ROM in `firmware/rom`, which is bare-metal C built with the SDK's compiler and no Zephyr; OpenSBI v1.9, for the host, with its `test_payload`; `firmware/sbi_payload`, a payload of ours for OpenSBI, built as the ROM is; and EDK2 `edk2-stable202608`, which is UEFI, built from its port for QEMU's RISC-V `virt` as `uefi.fd`, to run where OpenSBI jumps.

```sh
uv run firmware/build.py              # everything, into build/firmware
uv run firmware/build.py rom zephyr   # just those parts, and what they need
```

The parts are `sdk`, `llvm` and `zephyr-tree`, which fetch what the rest is built with, and `rom`, `opensbi`, `zephyr` and `edk2`, which build the images. Each fetches what it needs first, so naming one is enough, and `-j N` builds that many of Zephyr's images at once. CI builds the four kinds of image in four jobs side by side, each cached on what it is built from (`uv run python tools/ci.py --list` shows them).

- The script downloads the SDK's RISC-V toolchain (about 225 MB), the SDK's LLVM (about 260 MB, two gigabytes unpacked), OpenSBI, EDK2 with its submodules, Zephyr 4.4.2, and a Python for Zephyr's and EDK2's build scripts into `build/firmware` the first time, which takes a few minutes. After that it takes a minute or two, most of it EDK2's.
- 🎓 **OpenSBI is built with the SDK's LLVM and not its GCC.** OpenSBI runs wherever it is put, by being linked as a position-independent executable, and the SDK's GNU linker is built for bare-metal programs and cannot make one. LLVM's can, for any target. It is kept beside the SDK, in `build/firmware/llvm-<version>`, so that what copies or caches the SDK for Zephyr does not carry it.
- 🎓 **So is EDK2**, whose build links every module with `-z notext`, which the SDK's GNU linker refuses. Its `BaseTools` are built with the machine's own compiler, which is why it needs libuuid's headers, and a driver or two have ACPI tables that `iasl` compiles. The script says so and stops when there is no `iasl`.
- 📮 **OpenSBI's and EDK2's patches** are `cmake/patches/opensbi-*.patch` and `cmake/patches/edk2-*.patch`, each with its entry in [upstream.md](upstream.md), and the script applies them to a clean tree every time, so that a patch that changes is the one built.
- 💡 On an Apple silicon Mac the script runs on macOS itself: the SDK has a toolchain for one, and nothing else has to be installed but `iasl`. Every image builds in a minute there. ⚠️ EDK2's part of it has been run on Linux only so far: CI builds it there, and nothing builds it on a Mac yet.
- 💡 On an Intel Mac the same command works, and it needs Docker. The Zephyr SDK ships no macOS x86-64 toolchain, so there the script runs itself in the devcontainer's image, which is Linux and has one. It builds that image the first time, as `socpuppet-dev`. The images it leaves in `build/firmware` are plain RISC-V ELF files, so the tests on the Mac boot them as they are. Each run takes a few minutes there, not seconds: the files are the Mac's, and a container reaches them slowly.
- ⚠️ The script does not rebuild the image when `.devcontainer/Dockerfile` changes. `tools/devcontainer.sh` does, and names the new image `socpuppet-dev` too, so after such a change run `tools/devcontainer.sh true` once.
- ⚠️ The toolchain an Intel Mac ends up with in `build/firmware` is Linux's, GDB included. To debug from there, run GDB in the same image ([boot-your-firmware.md](boot-your-firmware.md#debugging-with-gdb) has the command).
- A test that needs an image you have not built is skipped, and says so. Set `SOCPUPPET_REQUIRE_FIRMWARE=1` to make it fail instead, which is what CI does.
- `SOCPUPPET_FIRMWARE_DIR` points the tests at images kept somewhere else.

`firmware/twister.sh` is the other thing to run there. It has twister, Zephyr's test runner, build Zephyr's own test suites and ours for each board and run every one on socpuppet, which is how a change to a model, a driver or a board is held to several thousand tests nobody here wrote. It takes six and a half minutes for the whole list on an Apple silicon Mac and about eight on an Intel one, where it runs in Docker, so it is for before a push and for CI, and not for the inner loop. [twister.md](twister.md) is its page.

```sh
firmware/twister.sh --suites                                   # everything, on every board
firmware/twister.sh -T python/socpuppet/zephyr_module/tests    # the drivers' own tests
```

## The package

```sh
uv build --wheel
uv run python tools/check_wheel.py dist/*.whl     # contents are what they should be
tools/test_wheel.sh uv dist/*.whl                 # install in a clean env, run the tests there
tools/test_wheel.sh pip dist/*.whl
```

The wheel is self-contained: SystemC, SCC and their dependencies are linked statically into the one extension module.

That wheel is for your own machine. The ones a user will install are built in CI by [cibuildwheel](https://cibuildwheel.pypa.io), as configured under `[tool.cibuildwheel]` in `pyproject.toml`: one per Python version, for Linux on Intel and Arm and for macOS on Apple silicon. 🎓 A Linux wheel has to run on many distributions, so it is built inside a deliberately old one (a "manylinux" container) and then checked to depend on nothing a distribution might lack. To try the build locally, which on Linux needs Docker:

```sh
uv run python tools/ci.py wheel     # this machine's wheel, for the pinned Python, into build/wheelhouse
```

- 💡 It builds from a source distribution and not from the checkout, because cibuildwheel copies the whole directory it is given into its container, and `build/` is far too big to copy.
- The macOS wheels need macOS 13.3 or newer. The code uses C++20's `std::format` for floating-point numbers, which the system's C++ library has had since that release.
- 🚧 Nothing is published yet. CI keeps the wheels as artifacts of each run.

## How changes are made

Test-first, following `.claude/skills/tdd`: state the behavior as "in scenario X, Y happens", write one test for it, watch it fail, then write just enough code. Tests are named for the scenario and the outcome, and drive real blocks through their public interfaces.

## Dependencies

Pinned in `cmake/Dependencies.cmake` and fetched at configure time. Third-party licenses are listed in `THIRD_PARTY_NOTICES.md`.

The register maps in `regs/` are compiled by [systemrdl-compiler](https://github.com/SystemRDL/systemrdl-compiler) (MIT), which `uv sync` installs with the linters. It is a developer's tool and not a dependency of the package: what `tools/regs.py` generates with it is checked in, so a build needs only a compiler and an installed socpuppet has no use for it. ⚠️ After changing a `.rdl`, run `uv run python tools/lint.py --fix`, and then `firmware/build.py`, because the firmware images are built from the generated headers too.

SCC needed a few accommodations to build inside this tree, each commented where it is made: two small patches (`cmake/patches/`), one to a configure-time probe and one so that clang-tidy can read the CCI headers it bundles, its install rules switched off, our SystemC declared as already found, and Boost.Filesystem linked explicitly.

QBox, the second CPU, is not fetched at all: `tools/build_qbox.sh` builds it at its pin, applying `cmake/patches/qbox-*.patch` to it and `libqemu-*.patch` to the QEMU it fetches ([QBox, the second hart](#qbox-the-second-hart)).

DBT-RISE-RISCV, the CPU model, is built by its own CMake as a static library, with the patches named `dbt-rise-*` in `cmake/patches/`, to it and to the core library under it, and a few accommodations of the same kind. ⚠️ `git apply` does not apply a patch twice. When a patch file changes, or a build tree still holds a dependency patched the old way, delete `build/<tree>/_deps/<dependency>-*` and configure again.

🎓 **Making a patch when others are stacked on the same file.** The patches of one project are applied in the order `cmake/Dependencies.cmake` lists them, each to what the ones before it left, so a new one is a diff against exactly that. Work in a build tree's copy (`build/dev/_deps/<dependency>-src`), which is a git checkout with every patch applied and nothing committed. To get the diff of yours alone, put the earlier patches in that checkout's index and compare the working tree with it: `git reset -q`, then `git apply --cached` each earlier patch in order, then `git diff > cmake/patches/<project>-<what>.patch`. ⚠️ Three things go wrong otherwise. A diff against the checkout's `HEAD` has every earlier patch in it. An index that still holds a draft of your own patch gives you only what changed since the draft. And to change a patch that has later ones stacked on it, take those out of the working tree first (`git apply -R`, last one first) and put them back afterwards. Then delete the dependency from the build tree and configure again, so that the whole list is applied from scratch, which is the test that it can be.

📮 A change to someone else's code is a `git apply` file in `cmake/patches/`, and the same commit adds an entry to [upstream.md](upstream.md) saying what is wrong, how to see it and what to propose. That page is the list to work from when the fixes are sent upstream.
