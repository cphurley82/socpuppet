#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <systemc>

#include "socpuppet/models/memory.h"
#include "socpuppet/models/pass_through_link.h"
#include "socpuppet/models/scripted_bus_master.h"

namespace py = pybind11;

namespace {

// (address, value) pairs, as Python passes them.
using Writes = std::vector<std::pair<std::uint64_t, std::uint32_t>>;

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

// The first end-to-end slice, wired by hand, from before the registry
// existed. It will be replaced by socpuppet::Platform (platform/platform.h): a scripted bus master writes
// through the pass-through link into a memory.
class Platform {
 public:
  explicit Platform(const Writes& writes) {
    master_.set_script(to_ops(writes));
    master_.socket.bind(link_.target);
    link_.initiator.bind(memory_.socket);
  }

  void run() { sc_core::sc_start(); }

  std::uint32_t peek32(std::uint64_t address) const { return memory_.peek32(address); }

 private:
  static std::vector<socpuppet::Write32> to_ops(
      const Writes& writes) {
    std::vector<socpuppet::Write32> ops;
    for (const auto& [address, value] : writes) ops.push_back({address, value});
    return ops;
  }

  KernelClaim kernel_claim_;  // first member: checked before any module is built
  socpuppet::ScriptedBusMaster master_{"master"};
  socpuppet::PassThroughLink link_{"link"};
  socpuppet::Memory memory_{"memory", 0x100};
};

}  // namespace

PYBIND11_MODULE(_core, m) {
  py::class_<Platform>(m, "Platform")
      .def(py::init<const Writes&>(),
           py::arg("writes"))
      .def("run", &Platform::run)
      .def("peek32", &Platform::peek32);
}
