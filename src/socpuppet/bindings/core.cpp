#include <cstddef>
#include <cstdint>
#include <exception>
#include <list>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <systemc>

#include "socpuppet/bindings/python_executor.h"
#include "socpuppet/bindings/python_script.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/logging.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/time_conversion.h"

namespace py = pybind11;

namespace {

// The SystemC kernel is a process-wide singleton that cannot be restarted,
// so the first Platform built in a process is the only one it can have.
struct KernelClaim {
  KernelClaim() {
    static bool claimed = false;
    if (claimed) {
      throw std::runtime_error(
          "A process can build only one Platform, because the SystemC kernel "
          "underneath it "
          "cannot be restarted. Build each Platform in its own process. In "
          "pytest, mark the "
          "test with @pytest.mark.platform, which does that for you (enable it "
          "with "
          "pytest_plugins = [\"socpuppet.pytest_plugin\"] in conftest.py).");
    }
    claimed = true;
  }
};

// What Python's Platform.build() drives: the C++ platform, plus the claim
// on this process's one kernel.
struct NativePlatform {
  explicit NativePlatform(bool color_log) { socpuppet::InitLogging(color_log); }

  // Runs part of the simulation with the GIL released, so that Python
  // scripts (and other Python threads) can run while the kernel does.
  template <typename Simulate>
  void WithoutGil(Simulate simulate) {
    py::gil_scoped_release release;
    simulate();
  }

  KernelClaim kernel_claim;  // first member: checked before any module is built
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  socpuppet::PythonExecutor python_executor{"socpuppet_python_executor"};
  // Declared last, so the Python scripts are dropped first, while the GIL is
  // held by whoever is destroying this platform from Python.
  std::list<socpuppet::PythonScript> python_scripts;
};

}  // namespace

PYBIND11_MODULE(_core, m) {
  // C++ failures that have a Python exception of their own. pybind11 fixes
  // the signature of a translator: it takes the exception_ptr by value.
  // NOLINTNEXTLINE(performance-unnecessary-value-param)
  py::register_exception_translator([](std::exception_ptr failure) {
    try {
      if (failure) std::rethrow_exception(failure);
    } catch (const socpuppet::ExpectationFailed& expectation) {
      py::object type =
          py::module_::import("socpuppet.errors").attr("ExpectationFailed");
      PyErr_SetString(type.ptr(), expectation.what());
    }
  });

  // implementations() and Platform.ports() exist so the Python catalogue can
  // be checked against the registry (tests/python/test_catalogue.py).
  m.def("implementations",
        [] { return socpuppet::BuiltinComponents().Implementations(); });

  py::class_<NativePlatform>(m, "Platform")
      .def(py::init<bool>(), py::arg("color_log"))
      .def("add",
           [](NativePlatform& self, const std::string& path,
              const std::string& implementation,
              const socpuppet::Config& config) {
             self.platform.Add(path, implementation, config);
           })
      .def("bind",
           [](NativePlatform& self, const std::string& source,
              const std::string& sink,
              bool traced) { self.platform.Bind(source, sink, traced); })
      // Each record is (time in ps, source, sink, is_write, address, data, ok).
      .def("trace_records",
           [](NativePlatform& self) {
             py::list records;
             for (const socpuppet::TraceRecord& each :
                  self.platform.RecordedTrace().Records()) {
               records.append(py::make_tuple(
                   each.time.count(), each.source, each.sink, each.is_write,
                   each.address,
                   py::bytes(reinterpret_cast<const char*>(each.data.data()),
                             each.data.size()),
                   each.ok));
             }
             return records;
           })
      .def("set_script",
           [](NativePlatform& self, const std::string& path,
              py::object generator_function) {
             socpuppet::PythonScript& script = self.python_scripts.emplace_back(
                 std::move(generator_function), self.python_executor);
             self.platform.ModuleAt<socpuppet::ScriptedBusMaster>(path)
                 .SetScript([&script] { return script.Play(); });
           })
      .def("ports",
           [](NativePlatform& self, const std::string& path) {
             return self.platform.Ports(path);
           })
      .def("elaborate", [](NativePlatform& self) { self.platform.Elaborate(); })
      .def("run",
           [](NativePlatform& self) {
             self.WithoutGil([&] { self.platform.Run(); });
           })
      .def("run_for",
           [](NativePlatform& self, std::uint64_t picoseconds) {
             self.WithoutGil([&] {
               self.platform.Run(
                   socpuppet::ToScTime(socpuppet::Picoseconds{picoseconds}));
             });
           })
      .def("step",
           [](NativePlatform& self) {
             bool stepped = false;
             self.WithoutGil([&] { stepped = self.platform.Step(); });
             return stepped;
           })
      // None when nothing is scheduled.
      .def("picoseconds_to_next_activity",
           [](NativePlatform& self) -> std::optional<std::uint64_t> {
             std::optional<sc_core::sc_time> ahead;
             self.WithoutGil(
                 [&] { ahead = self.platform.TimeToNextActivity(); });
             if (!ahead) return std::nullopt;
             return socpuppet::ToPicoseconds(*ahead).count();
           })
      .def("time_in_picoseconds",
           [](NativePlatform& self) {
             return socpuppet::ToPicoseconds(self.platform.Time()).count();
           })
      // debug_read returns None, and debug_write False, when nothing took the
      // access.
      .def("debug_read",
           [](NativePlatform& self, const std::string& via,
              std::uint64_t address, std::size_t length) -> py::object {
             std::string data(length, '\0');
             if (!self.platform.DebugRead(
                     via, address, std::as_writable_bytes(std::span{data}))) {
               return py::none();
             }
             return py::bytes(data);
           })
      .def("debug_write", [](NativePlatform& self, const std::string& via,
                             std::uint64_t address, const std::string& data) {
        return self.platform.DebugWrite(via, address,
                                        std::as_bytes(std::span{data}));
      });
}
