# Style, and the tools that hold us to it

socpuppet is meant to be read. A learner should be able to open any file and find it laid out like every other file, so the code follows published style guides and tools check it. Nobody has to remember the rules: most are applied for you when you build, and the rest are reported by one command.

## The short version

| Language | Style | Checked by |
|---|---|---|
| C++ | [Google C++ Style Guide](https://google.github.io/styleguide/cppguide.html) | clang-format, cpplint, clang-tidy, the compiler's warnings |
| C, for Zephyr | [Zephyr's coding style](https://docs.zephyrproject.org/latest/contribute/style/index.html) | clang-format, Zephyr's own build |
| Python | [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) for docstrings, ruff's formatter for layout | ruff, mypy |
| Markdown | one paragraph per line | rumdl |
| SystemRDL, for register maps | one block to a file, in `regs/` | `tools/regs.py`, which lint runs |
| CI workflows, shell scripts | | actionlint, shellcheck |

```sh
uv run python tools/lint.py          # every linter, over the whole tree
uv run python tools/lint.py --fix    # the same, repairing what can be repaired
```

`uv sync` installs all of these tools, at pinned versions, next to cmake and ninja. There is nothing else to install.

## What happens when

| When you run | This happens |
|---|---|
| `uv run cmake --build --preset dev` | C++ and Python are formatted in place, then our code is compiled with warnings as errors. |
| `uv run ctest --preset dev` | Every test, plus a `lint` test that runs all the linters, plus the tests of the tooling itself. |
| `uv run python tools/lint.py [--fix] [linter ...]` | The linters on their own. Nothing needs to be built first. Name linters to run only those. |
| `uv run cmake --build --preset dev --target tidy` | clang-tidy over our C++. About 40 seconds. |
| `uv run cmake --build --preset dev --target check_headers` | Each of our headers compiled on its own. |

CI runs all of it on every push. 💡 In CI the build does not format anything: a misformatted file fails the lint job there, so that it gets fixed in the repository and not in a checkout that is about to be thrown away.

## C++

Google style, as written. The parts you will meet most:

| Thing | Looks like |
|---|---|
| Types, functions, methods | `MemoryStore`, `Elaborate()`, `PortAt()` |
| Variables, parameters, struct members | `address`, `read_back` |
| Private and protected members | `bytes_` |
| Constants and enumerators | `kLowRamBase`, `Outcome::kCarryOn` |
| Namespaces | `socpuppet` |
| Header guard | `SOCPUPPET_CORE_TIME_H_` for `src/socpuppet/core/time.h` |
| Line length | 80 columns |

Includes come in groups, each sorted: the header a file implements or tests, then C system headers, then the C++ standard library, then third-party libraries (`<systemc>`, `<tlm>`, `<gtest/gtest.h>`), then our own. Our own are written with their path from `src/`, as `"socpuppet/core/time.h"`. clang-format does the grouping and sorting for you.

### Where we differ from Google, and why

- **Exceptions are used.** pybind11 turns a C++ exception into a Python one, which is how an error in a model reaches your script, and SystemC reports its own errors by throwing.
- **`dynamic_cast` is used, in one place.** The platform is wired up by name at run time. A port says which of the four things it is (a `std::variant`), so binding needs no cast. A component is held as a plain `sc_module`, and `Platform::ModuleAt<T>` casts it back for a C++ caller that knows the type, with an error that names both types if it is another.
- **Source files end in `.cpp`,** not `.cc`.
- **SystemC modules have public data members:** their sockets and ports. Binding is done from outside the module, and this is how every SystemC model is written.
- **Some names are not ours to choose,** and keep the spelling their owner gave them:
  - TLM-2.0's transport functions (`b_transport`, `transport_dbg`, `get_direct_mem_ptr`). 🎓 Anyone who has met TLM in another tool will look for these names.
  - SystemC's callbacks, such as `before_end_of_elaboration`.
  - The functions the compiler calls on a coroutine (`await_transform`, `promise_type` and the rest, in `core/script.h`).
- **No copyright line in each file.** The `LICENSE` file covers the repository.
- **Most code is in headers.** Our own models are header-only, so function bodies sit in class definitions where Google would move the longer ones to a `.cpp` file. The exceptions have a reason: a borrowed model's adapter (`models/plic.cpp` and its siblings) keeps the third-party headers out of everything else, a core with a borrowed header (`core/nvme_controller.cpp`, `core/elf_image.cpp`) does the same, and the platform builder (`platform/platform.cpp`) is included by everything that composes a platform and has no reason to be compiled each time.

### The C++ tools

- **clang-format** lays the code out. Its settings are in `.clang-format`: Google's, plus the include order above.
- **cpplint** is Google's own linter. It checks what clang-format cannot: header guards, `using namespace`, include paths. Its settings are in `CPPLINT.cfg`.
- **The compiler** runs with `-Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wsign-conversion`, and a warning in our code fails the build. Warnings inside dependencies are not our business and are not shown.
- **clang-tidy** looks for likely bugs, slow code and code that newer C++ can say more simply, and it is what enforces the naming table above. Its checks are listed in `.clang-tidy`, and every check that is switched off has its reason written next to it. When a finding is wrong for one line, say so on that line:

  ```cpp
  // pybind11 fixes the signature of a translator: it takes the pointer by value.
  // NOLINTNEXTLINE(performance-unnecessary-value-param)
  ```

- **`check_headers`** compiles each header alone, which shows that it includes everything it uses.

## C, for Zephyr

The firmware in `firmware/` and the drivers in socpuppet's Zephyr module (`python/socpuppet/zephyr_module/`) are C, and they follow Zephyr's style and not the C++ code's: tabs, braces the way the Linux kernel has them, 100 columns, `snake_case` names, `/* */` comments.

💡 Why a second style? That code is read next to Zephyr's own. A driver is written by looking at the driver beside it, and it is what would be sent upstream. Code in the house style of the tree it lives in is easier to read there than code that is consistent with a simulator the reader has never seen.

- **clang-format** lays it out, as it does the C++. Each of the two directories has a `.clang-format` of its own with Zephyr's settings, and clang-format goes by the nearest one.
- **cpplint is not run on it.** It checks Google's C++ style. A `CPPLINT.cfg` in each directory says to leave the files alone.
- **Zephyr's build** compiles it, with Zephyr's warnings. `firmware/build.sh` builds every image the tests boot.
- A header's guard is the header's name as Zephyr would spell it, such as `SOCPUPPET_DRIVERS_DMA_ENGINE_H_`, and not its path from `src/`.
- **A driver's functions are named for its device**: `nvme_frontend_wait`, `dma_engine_copy_to_host`. C has one namespace, so where the device's own name is one Zephyr already uses for a whole subsystem, the name starts with `socpuppet_`, as `socpuppet_pcie_*` does. The header says whose it is either way: `<socpuppet/drivers/nvme_frontend.h>`.

## Python

- **ruff format** lays the code out, at 80 columns to match the C++.
- **ruff** lints it: unused imports, import order, likely bugs, naming, docstrings in Google's convention. The rule families are listed in `ruff.toml`. Tests need no docstrings, because a test's name already states the scenario and the outcome, and that makes for names longer than a line, which is fine.
- **mypy** type-checks the `socpuppet` package in strict mode, so every function says what it takes and returns. The package ships `py.typed`, so your own scripts are checked against those types too. 💡 `python/socpuppet/_core.pyi` describes the C++ extension to the type checker, which cannot read a compiled module. If you change the bindings in `src/socpuppet/bindings/core.cpp`, change it to match.

## Markdown

**One paragraph is one line**, however long. Your editor wraps it for display. 💡 Hard-wrapped prose makes a one-word change look like a rewritten paragraph in a diff. rumdl checks the structure (heading levels, blank lines around lists and code blocks, a language on every code block) and has its line-length rule switched off in `.rumdl.toml`.

## SystemRDL

A block's register map is `regs/<block>.rdl`, and everything else that knows a register of that block is generated from it ([architecture.md](architecture.md#where-the-hardwaresoftware-interface-is-written-down) has the picture). 🎓 SystemRDL is the language the industry writes register maps in, so what you learn reading one of these is what you will meet elsewhere.

- **One `addrmap` to a file, named after the file.** The name is in every generated name: `DMA_ENGINE_STATUS_BUSY` in C, and `dma_engine.STATUS_BUSY` in Python.
- **Names are `UPPER_SNAKE`**, as a datasheet has them, and a field's generated name is its register's and then its own. A field that is the whole of its register is called `VALUE`, and is left out of the names: the register's name is enough.
- **`block_size` says how many bytes the block takes**, which is the range a board gives it. SystemRDL has no word for that, so it is a property of ours (`regs/properties.rdl`).
- **A description is a sentence, with its full stop.** The table on the block's page joins a register's description to its fields', so each has to stand on its own.
- **A register two blocks share is a named type** in the file of the block that shares it, which the others include. `tools/regs.py` refuses a map that has it at another offset.
- **Generated files are not edited.** Each says so at the top. `uv run python tools/lint.py --fix` writes them again, and lint fails while one is not what its map gives.
- **In C++ a register is called by its generated name**, a macro, and not by a constant of ours beside it. 💡 Google style has no time for macros, and this is the one place they are used: the header is C, because the Zephyr driver includes the same file, and one name for a register in every language is what makes it possible to find everything that touches it.

## How the tooling is tested

The lint runner and the CMake module that adds the build-time checks are code like any other, so they have tests, in `tests/tooling/`. Each test builds a throwaway git repository or a small CMake project, puts one bad file in it, and checks that the tool objects. They use the repository's real configuration files, so they also pin the rules themselves: one test fails if an 81-column line is ever accepted.
