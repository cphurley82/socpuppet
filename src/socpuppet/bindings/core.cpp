#include <cstddef>
#include <cstdint>
#include <span>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <systemc>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/logging.h"
#include "socpuppet/platform/platform.h"

namespace py = pybind11;

namespace {

// The SystemC kernel is a process-wide singleton that cannot be restarted,
// so the first Platform built in a process is the only one it can have.
struct KernelClaim {
  KernelClaim() {
    static bool claimed = false;
    if (claimed) {
      throw std::runtime_error(
          "A process can build only one Platform, because the SystemC kernel underneath it "
          "cannot be restarted. Build each Platform in its own process. In pytest, mark the "
          "test with @pytest.mark.platform, which does that for you (enable it with "
          "pytest_plugins = [\"socpuppet.pytest_plugin\"] in conftest.py).");
    }
    claimed = true;
  }
};

// What Python's Platform.build() drives: the C++ platform, plus the claim
// on this process's one kernel.
struct NativePlatform {
  explicit NativePlatform(bool color_log) { socpuppet::init_logging(color_log); }

  KernelClaim kernel_claim;  // first member: checked before any module is built
  socpuppet::Platform platform{socpuppet::builtin_components()};
};

// sc_time counts in units of the kernel's time resolution. This is how many
// of those make a picosecond, the unit Python uses.
std::uint64_t one_picosecond() { return sc_core::sc_time(1, sc_core::SC_PS).value(); }

// (address, value) pairs, as Python passes them.
using Writes = std::vector<std::pair<std::uint64_t, std::uint32_t>>;

// A script that carries out the writes in order. Takes the list by value,
// as every coroutine must (see core/script.h).
socpuppet::Script write_each(Writes writes) {
  for (const auto& [address, value] : writes) co_await socpuppet::write32(address, value);
}

}  // namespace

PYBIND11_MODULE(_core, m) {
  // implementations() and Platform.ports() exist so the Python catalogue can
  // be checked against the registry (tests/python/test_catalogue.py).
  m.def("implementations", [] { return socpuppet::builtin_components().implementations(); });

  py::class_<NativePlatform>(m, "Platform")
      .def(py::init<bool>(), py::arg("color_log"))
      .def("add",
           [](NativePlatform& self, const std::string& path, const std::string& implementation,
              const socpuppet::Config& config) {
             self.platform.add(path, implementation, config);
           })
      .def("bind", [](NativePlatform& self, const std::string& source,
                      const std::string& sink) { self.platform.bind(source, sink); })
      .def("set_writes",
           [](NativePlatform& self, const std::string& path, const Writes& writes) {
             self.platform.module<socpuppet::ScriptedBusMaster>(path).set_script(
                 [writes] { return write_each(writes); });
           })
      .def("ports", [](NativePlatform& self,
                       const std::string& path) { return self.platform.ports(path); })
      .def("elaborate", [](NativePlatform& self) { self.platform.elaborate(); })
      .def("run", [](NativePlatform& self) { self.platform.run(); })
      .def("run_for",
           [](NativePlatform& self, std::uint64_t picoseconds) {
             self.platform.run(sc_core::sc_time::from_value(picoseconds * one_picosecond()));
           })
      .def("time_in_picoseconds",
           [](NativePlatform& self) { return self.platform.time().value() / one_picosecond(); })
      // debug_read returns None, and debug_write False, when nothing took the access.
      .def("debug_read",
           [](NativePlatform& self, const std::string& via, std::uint64_t address,
              std::size_t length) -> py::object {
             std::string data(length, '\0');
             if (!self.platform.debug_read(via, address, std::as_writable_bytes(std::span{data}))) {
               return py::none();
             }
             return py::bytes(data);
           })
      .def("debug_write",
           [](NativePlatform& self, const std::string& via, std::uint64_t address,
              const std::string& data) {
             return self.platform.debug_write(via, address, std::as_bytes(std::span{data}));
           });
}
