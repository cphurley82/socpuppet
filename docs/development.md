# Building and testing socpuppet

## What you need

💡 Setting up a machine for the first time? [Setting up a machine for development](setup.md) goes from a bare install to every test passing, QBox included, step by step.

- A C++20 compiler: GCC 13 or newer, or a recent Clang (Apple clang works).
- [uv](https://docs.astral.sh/uv/). It supplies Python, CMake and Ninja, so none of those need installing.
- git, and zlib's headers (`zlib1g-dev` on Ubuntu; already there on macOS).
- `dtc`, the devicetree compiler (`device-tree-compiler` on Ubuntu, `brew install dtc` on macOS). Two Python tests that check generated devicetrees skip without it.

Ubuntu 24.04 and macOS are both supported and both run in CI. If you would rather not set anything up, open the repo in the devcontainer (`.devcontainer/`), which is the CI environment.

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
tools/devcontainer.sh uv run cmake -S . -B build/linux -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DSOCPUPPET_DEVELOPER_MODE=ON
tools/devcontainer.sh uv run cmake --build build/linux
```

💡 `tools/devcontainer.sh` runs any command in the devcontainer's image, with the repository at `/workspace` (`tools/devcontainer.sh bash` is a shell there). It names the image after a hash of `.devcontainer/Dockerfile`, so it builds the image the first time and again whenever the Dockerfile changes. uv's Linux venv, its cache and its Python are kept in `build/`, so they outlive each container, and your `SOCPUPPET_*` variables go in with the command. ⚠️ A second build tree has its own copy of every dependency, patched when it was fetched. After a change to a file in `cmake/patches/`, that tree's copy is stale too: delete it and configure again, as [Dependencies](#dependencies) says. `firmware/twister.sh` keeps the same tree, `build/linux`, on an Intel Mac, and does that by itself.

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
- 💡 The nightly workflow (`.github/workflows/qbox.yml`) does all of this, with clang-tidy over the adapter and twister on the host board, every night and when run by hand: `gh workflow run qbox.yml`.
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

Some tests boot real firmware: Zephyr samples and applications of ours, built with the Zephyr SDK, and the boot ROM in `firmware/rom`, which is bare-metal C built with the SDK's compiler and no Zephyr.

```sh
firmware/build.sh        # into build/firmware
```

- The script downloads the SDK's RISC-V toolchain (about 225 MB), Zephyr 4.4.2, and a Python for Zephyr's build scripts into `build/firmware` the first time, which takes a few minutes. After that it takes seconds.
- 💡 On an Apple silicon Mac the script runs on macOS itself: the SDK has a toolchain for one, and nothing else has to be installed. Every image builds in a minute there.
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

That wheel is for your own machine. The ones a user will install are built in CI by [cibuildwheel](https://cibuildwheel.pypa.io), as configured under `[tool.cibuildwheel]` in `pyproject.toml`: one per Python version, for Linux on Intel and Arm and for macOS on Apple silicon. 🎓 A Linux wheel has to run on many distributions, so it is built inside a deliberately old one (a "manylinux" container) and then checked to depend on nothing a distribution might lack. To try the Linux build locally you need Docker:

```sh
uvx cibuildwheel --only cp313-manylinux_aarch64   # or cp313-manylinux_x86_64
```

- ⚠️ cibuildwheel copies the whole directory into its container, `build/` included. Run it from a clean checkout, or expect a long wait.
- The macOS wheels need macOS 13.3 or newer. The code uses C++20's `std::format` for floating-point numbers, which the system's C++ library has had since that release.
- 🚧 Nothing is published yet. CI keeps the wheels as artifacts of each run.

## How changes are made

Test-first, following `.claude/skills/tdd`: state the behavior as "in scenario X, Y happens", write one test for it, watch it fail, then write just enough code. Tests are named for the scenario and the outcome, and drive real blocks through their public interfaces.

## Dependencies

Pinned in `cmake/Dependencies.cmake` and fetched at configure time. Third-party licenses are listed in `THIRD_PARTY_NOTICES.md`.

The register maps in `regs/` are compiled by [systemrdl-compiler](https://github.com/SystemRDL/systemrdl-compiler) (MIT), which `uv sync` installs with the linters. It is a developer's tool and not a dependency of the package: what `tools/regs.py` generates with it is checked in, so a build needs only a compiler and an installed socpuppet has no use for it. ⚠️ After changing a `.rdl`, run `uv run python tools/lint.py --fix`, and then `firmware/build.sh`, because the firmware images are built from the generated headers too.

SCC needed a few accommodations to build inside this tree, each commented where it is made: two small patches (`cmake/patches/`), one to a configure-time probe and one so that clang-tidy can read the CCI headers it bundles, its install rules switched off, our SystemC declared as already found, and Boost.Filesystem linked explicitly.

QBox, the second CPU, is not fetched at all: `tools/build_qbox.sh` builds it at its pin, applying `cmake/patches/qbox-*.patch` to it and `libqemu-*.patch` to the QEMU it fetches ([QBox, the second hart](#qbox-the-second-hart)).

DBT-RISE-RISCV, the CPU model, is built by its own CMake as a static library, with the patches named `dbt-rise-*` in `cmake/patches/`, to it and to the core library under it, and a few accommodations of the same kind. ⚠️ `git apply` does not apply a patch twice. When a patch file changes, or a build tree still holds a dependency patched the old way, delete `build/<tree>/_deps/<dependency>-*` and configure again.

🎓 **Making a patch when others are stacked on the same file.** The patches of one project are applied in the order `cmake/Dependencies.cmake` lists them, each to what the ones before it left, so a new one is a diff against exactly that. Work in a build tree's copy (`build/dev/_deps/<dependency>-src`), which is a git checkout with every patch applied and nothing committed. To get the diff of yours alone, put the earlier patches in that checkout's index and compare the working tree with it: `git reset -q`, then `git apply --cached` each earlier patch in order, then `git diff > cmake/patches/<project>-<what>.patch`. ⚠️ Three things go wrong otherwise. A diff against the checkout's `HEAD` has every earlier patch in it. An index that still holds a draft of your own patch gives you only what changed since the draft. And to change a patch that has later ones stacked on it, take those out of the working tree first (`git apply -R`, last one first) and put them back afterwards. Then delete the dependency from the build tree and configure again, so that the whole list is applied from scratch, which is the test that it can be.

📮 A change to someone else's code is a `git apply` file in `cmake/patches/`, and the same commit adds an entry to [upstream.md](upstream.md) saying what is wrong, how to see it and what to propose. That page is the list to work from when the fixes are sent upstream.
