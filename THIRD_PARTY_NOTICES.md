# Third-party notices

socpuppet itself is MIT licensed (see `LICENSE`). Its binary wheel links the
following third-party code statically into the `socpuppet._core` extension.
Each is used unmodified except where noted.

| Component | License | Source |
|---|---|---|
| SystemC 3.0.2 | Apache-2.0 | <https://github.com/accellera-official/systemc> |
| SystemC-Components (SCC) 2026.07, with a one-line build patch (`cmake/patches/`) | Apache-2.0 | <https://github.com/Minres/SystemC-Components> |
| SystemC CCI, bundled with SCC, with two constructors made `explicit` (`cmake/patches/`) | Apache-2.0 | <https://github.com/accellera-official/cci> |
| LWTR4SC, bundled with SCC | Apache-2.0 | <https://github.com/Minres/LWTR4SC> |
| RapidJSON, bundled with SCC | MIT | <https://github.com/Tencent/rapidjson> |
| lz4, bundled with SCC | BSD-2-Clause | <https://github.com/lz4/lz4> |
| Boost 1.89.0 | BSL-1.0 | <https://www.boost.org> |
| {fmt} 12.0.0 | MIT | <https://github.com/fmtlib/fmt> |
| spdlog 1.16.0 | MIT | <https://github.com/gabime/spdlog> |
| yaml-cpp 0.8.0 | MIT | <https://github.com/jbeder/yaml-cpp> |
| pybind11 3.1.0 | BSD-3-Clause | <https://github.com/pybind/pybind11> |
| DBT-RISE-RISCV 2.1.0, with five patches (`cmake/patches/`) | BSD-3-Clause | <https://github.com/Minres/DBT-RISE-RISCV> |
| DBT-RISE-Core, with two patches (`cmake/patches/`) | BSD-3-Clause | <https://github.com/Minres/DBT-RISE-Core> |
| softvector, with DBT-RISE-RISCV | BSD-3-Clause | <https://github.com/Minres/softvector> |
| Berkeley SoftFloat 3e, with softvector | BSD-3-Clause | <https://github.com/ucb-bar/berkeley-softfloat-3> |
| ELFIO 3.12 | MIT | <https://github.com/serge1/ELFIO> |
| VPV-Peripherals (the PULPino UART model) | Apache-2.0 | <https://github.com/VP-Vibes/VPV-Peripherals> |

The full license texts are available at the links above.
