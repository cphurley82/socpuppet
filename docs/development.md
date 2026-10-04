# Building and testing socpuppet

## What you need

- A C++20 compiler: GCC 13 or newer, or a recent Clang (Apple clang works).
- [uv](https://docs.astral.sh/uv/). It supplies Python, CMake and Ninja, so none of those need installing.
- git, and zlib's headers (`zlib1g-dev` on Ubuntu; already there on macOS).

Ubuntu 24.04 and macOS are both supported and both run in CI. If you would rather not set anything up, open the repo in the devcontainer (`.devcontainer/`), which is the CI environment.

## The loop

```
uv sync                                  # tools: Python, cmake, ninja, pytest
uv run cmake --preset dev                # configure (fetches the dependencies the first time)
uv run cmake --build --preset dev        # build
uv run ctest --preset dev                # every test: C++ and Python
```

⚠️ The first build takes several minutes: SystemC, SCC and the parts of Boost that SCC needs are compiled from source. After that, builds are incremental.

The build puts the Python extension next to the Python sources, so the package runs straight from the tree:

```
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

💡 "One process per test" is because the SystemC kernel cannot be restarted. Run the C++ kernel tests through `ctest`, not by launching the test binary by hand: launched directly, the second test in the binary would find the kernel already used.

## The package

```
uv build --wheel
uv run python tools/check_wheel.py dist/*.whl     # contents are what they should be
tools/test_wheel.sh uv dist/*.whl                 # install in a clean env, run the tests there
tools/test_wheel.sh pip dist/*.whl
```

The wheel is self-contained: SystemC, SCC and their dependencies are linked statically into the one extension module.

## How changes are made

Test-first, following `.claude/skills/tdd`: state the behavior as "in scenario X, Y happens", write one test for it, watch it fail, then write just enough code. Tests are named for the scenario and the outcome, and drive real blocks through their public interfaces.

## Dependencies

Pinned in `cmake/Dependencies.cmake` and fetched at configure time. Third-party licenses are listed in `THIRD_PARTY_NOTICES.md`.

SCC needed three accommodations to build inside this tree, each commented where it is made: a one-line patch to a configure-time probe (`cmake/patches/`), its install rules switched off, and Boost.Filesystem linked explicitly.
