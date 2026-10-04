#include <cstdint>
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

// The first end-to-end slice, wired by hand: a scripted bus master writes
// through the pass-through link into a memory.
class Platform {
 public:
  explicit Platform(const Writes& writes)
      : master_{"master", to_ops(writes)} {
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

  socpuppet::ScriptedBusMaster master_;
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
