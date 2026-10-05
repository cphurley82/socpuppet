# Building and testing socpuppet

## What you need

- A C++20 compiler: GCC 13 or newer, or a recent Clang (Apple clang works).
- [uv](https://docs.astral.sh/uv/). It supplies Python, CMake and Ninja, so none of those need installing.
- git, and zlib's headers (`zlib1g-dev` on Ubuntu; already there on macOS).

Ubuntu 24.04 and macOS are both supported and both run in CI. If you would rather not set anything up, open the repo in the devcontainer (`.devcontainer/`), which is the CI environment.

## The loop

```sh
uv sync                                  # tools: Python, cmake, ninja, pytest, the linters
uv run cmake --preset dev                # configure (fetches the dependencies the first time)
uv run cmake --build --preset dev        # format, then build
uv run ctest --preset dev                # every test: C++, Python, lint
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

## One build tree, four kinds of build

⚠️ The `dev`, `coverage`, `asan` and `spike` presets share `build/dev`, so that SystemC and the other dependencies are compiled only once. The tree holds whichever kind was configured last, and `cmake --build` does not change that. After a coverage, sanitizer or spike run, go back with:

```sh
uv run cmake --preset dev
```

Configuring prints a note when the tree is in one of the two special modes.

## Spikes

Sometimes the honest way to answer a design question is to try it. Code written for that lives under `spikes/`, and it is deliberately held to different rules from the rest of the tree: it is not written test-first, nothing in `src/`, `python/` or `tests/` may depend on it, and it is deleted once the question is answered. It is still linted and still built with warnings as errors.

```sh
uv run cmake --preset spike
uv run cmake --build --preset spike
uv run ctest --preset spike              # only the tests labelled `spike`
```

The `spike` preset is the `dev` build plus `spikes/`, in the same build tree. The everyday presets leave it out, and so do coverage and the wheel. What each spike is for is in its own README, for example [spikes/iss](../spikes/iss/README.md).

## Firmware

Some tests boot real firmware: Zephyr samples, built with the Zephyr SDK.

```sh
firmware/build.sh        # into build/firmware
```

- The script downloads the SDK's RISC-V toolchain (about 225 MB) and Zephyr 4.4.2 into `build/firmware` the first time, which takes a few minutes. After that it takes seconds.
- A test that needs an image you have not built is skipped, and says so. Set `SOCPUPPET_REQUIRE_FIRMWARE=1` to make it fail instead, which is what CI does.
- `SOCPUPPET_FIRMWARE_DIR` points the tests at images kept somewhere else.

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

SCC needed a few accommodations to build inside this tree, each commented where it is made: two small patches (`cmake/patches/`), one to a configure-time probe and one so that clang-tidy can read the CCI headers it bundles, its install rules switched off, our SystemC declared as already found, and Boost.Filesystem linked explicitly.

DBT-RISE-RISCV, the CPU model, is built by its own CMake as a static library, with seven patches and a few accommodations of the same kind. ⚠️ `git apply` does not apply a patch twice. When a patch file changes, or a build tree still holds a dependency patched the old way, delete `build/<tree>/_deps/<dependency>-*` and configure again.

📮 A change to someone else's code is a `git apply` file in `cmake/patches/`, and the same commit adds an entry to [upstream.md](upstream.md) saying what is wrong, how to see it and what to propose. That page is the list to work from when the fixes are sent upstream.
