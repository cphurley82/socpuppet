# The PCIe spike 🚧

Milestone M2 needs a PCIe endpoint: the part of a device that owns configuration space, the base address registers (BARs) and the MSI-X table, and turns the function's interrupt lines into messages. This spike asks one question: can [VCML](https://github.com/machineware-gmbh/vcml)'s PCI model be that endpoint, behind an adapter of ours, or do we write our own? The report, with the measurements and a recommendation, is [docs/pcie-spike.md](../../docs/pcie-spike.md).

🎓 VCML (MachineWare, Apache-2.0) is a library of SystemC models with its own socket types on top of TLM. Its PCI model comes in two halves that talk over one of those sockets: `vcml::pci::host`, which is the root complex's side, and `vcml::pci::endpoint`.

⚠️ Nothing here is part of socpuppet. It is exploratory code:

- No preset, CI job or wheel builds it. It has a CMake project of its own, with a build directory of its own.
- Nothing under `src/`, `python/` or `tests/` may include or import it.
- It is not written test-first and does not count towards coverage.
- It includes socpuppet's platform headers and the tests' NVMe host, and builds a copy of the Python extension from `src/socpuppet/bindings/core.cpp`. A change there can break it without anything saying so. Run it again before building on it.

## What is here

| Path | What |
|---|---|
| `Vcml.cmake` | The recipe: VCML and its support library, mwr, both pinned to release `v2026.10.02`, with everything optional switched off. |
| `pin_probe/` | A project that only configures, to try the four ways of getting mwr (three pinned, one not). |
| `vcml_endpoint.h`, `.cpp` | 🎭 The first adapter: `vcml::pci::host` wired to `vcml::pci::endpoint` in one module, with only plain TLM sockets and wires on the outside. |
| `vcml_bare_endpoint.h`, `.cpp` | 🎭 The second adapter: the endpoint alone, with the adapter playing the host's part towards it. This is the shape socpuppet's design would need, because its root complex is a component of its own. |
| `vcml_parts.h` | What the two share, including the three corrections VCML's endpoint needs. Only the adapters' source files may include it. |
| `components.h` | Adds the endpoint to socpuppet's registry as `vcml_pcie_endpoint`. |
| `test_support.h`, `rig.h` | The test platform: a host with memory, a spy on the endpoint's DMA, a catcher for MSI-X messages, and a stand-in function whose interrupt lines the test moves by hand. |
| `endpoint_test.cpp` | The report's questions as tests, built twice: once for each adapter. A test whose name starts with `Waiting` prints measurements and checks nothing. |
| `as_is_test.cpp` | VCML without the adapter's corrections. These tests pass while VCML misbehaves the way the report says, so a release that fixes one turns its test red. |
| `python_demo.py` | A Python script in the host's CPU slot that enumerates the endpoint, enables the behavioral NVMe controller behind it and gets an Identify completion with its MSI-X message. |

## Running it

Everything is built in `build/spike-pcie`. If the main build has run, its downloaded dependencies in `build/dev/_deps` are read where they are, and only VCML and mwr are fetched. The first build takes about five minutes with eight jobs, most of it socpuppet's own dependencies.

```sh
uv run cmake -S spikes/pcie -B build/spike-pcie -G Ninja -DCMAKE_BUILD_TYPE=Release
uv run cmake --build build/spike-pcie
uv run ctest --test-dir build/spike-pcie
```

💡 Each test builds a platform, and a process can build only one, so run them through `ctest`. To read what one test prints, run it alone:

```sh
build/spike-pcie/spike_pcie_tests --gtest_filter=Waiting.InsideBTransportWithNoQuantum
```

The Python demo runs on `_core_vcml`, a copy of socpuppet's extension that also links the adapter, VCML and mwr. `build/spike-pcie/python-vcml` holds it together with a `socpuppet` package that uses it:

```sh
PYTHONPATH=build/spike-pcie/python-vcml uv run python spikes/pcie/python_demo.py
```

socpuppet's own Python tests run on that extension too, which shows that linking VCML in leaves the rest alone:

```sh
PYTEST_ADDOPTS="-p no:cacheprovider -o pythonpath=build/spike-pcie/python-vcml" \
  uv run python -m pytest tests/python -q
```

For the size of the extension with and without VCML, build the unchanged one next to it and compare. A Release build strips both the same way.

```sh
uv run cmake --build build/spike-pcie --target _core
ls -l build/spike-pcie/python/_core.*.so build/spike-pcie/python-vcml/_core_vcml.*.so
```

The pinning probe configures in a few seconds. `target`, `home` and `tag` are three ways to pin mwr, and `none` is what VCML does when left alone:

```sh
uv run cmake -S spikes/pcie/pin_probe -B build/spike-pcie/pin-target -G Ninja -DSPIKE_MWR_PIN=target
```

⚠️ Linux was not tried: the machine the spike ran on (macOS, x86-64) has no Docker.
