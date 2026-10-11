#ifndef SPIKES_NPU_HEXAGON_INTEGRATION_HEXAGON_NPU_H_
#define SPIKES_NPU_HEXAGON_INTEGRATION_HEXAGON_NPU_H_

#include <cstdint>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

#include <cciutils.h>
#include <hexagon.h>
#include <hexagon_globalreg.h>
#include <hexagon_tlb.h>
#include <qemu-instance.h>
#include <systemc>
#include <tlm>

#include "socpuppet/models/memory.h"
#include "spikes/iss/qbox/harness/simple_router.h"
#include "spikes/npu/accelerator_slot.h"
#include "spikes/npu/doorbell_module.h"
#include "tests/cpp/support/bus_driver.h"

namespace spike {

// QBox's Hexagon behind the draft accelerator slot: a real programmable
// DSP, running a program somebody compiled for it (firmware/matmul.c),
// with the doorbell between it and the host. What the host sees is the
// slot: the doorbell's registers at `cpu`, the core's reads and writes of
// the host's memory through `socket`, and the doorbell's `irq`.
//
// Inside, the core has a bus of its own, as a DSP on a real SoC has:
//
//   0x0000_0000  256 MiB   the host's memory, out through `socket`
//   0x4000_0000    1 MiB   program memory, where the core starts
//   0x5000_0000             the doorbell's accelerator face
//
// QBox's components are configured through CCI parameters, set by name
// before the component is built, as the ISS spike's QboxCpu does.
class HexagonNpu : public sc_core::sc_module {
 public:
  static constexpr std::uint64_t kHostWindowSize = 0x1000'0000;
  static constexpr std::uint64_t kProgramBase = 0x4000'0000;
  static constexpr std::uint64_t kProgramSize = 0x10'0000;
  static constexpr std::uint64_t kDoorbellBase = 0x5000'0000;

  tlm::tlm_initiator_socket<> socket{"socket"};
  tlm::tlm_target_socket<> cpu{"cpu"};
  sc_core::sc_out<bool> irq{"irq"};

  HexagonNpu(const sc_core::sc_module_name& name, const std::string& program)
      : sc_module(name),
        configured_(Configure(this->name())),
        instance_("instance", &manager_, QemuInstance::Target::HEXAGON),
        global_registers_("global_registers", instance_),
        tlb_("tlb", instance_),
        core_("core", instance_, &global_registers_, nullptr, &tlb_),
        router_("router",
                {{.base = 0, .size = kHostWindowSize},
                 {.base = kProgramBase, .size = kProgramSize},
                 {.base = kDoorbellBase, .size = kDoorbellBlockSize}}),
        program_("program", kProgramSize) {
    global_registers_.p_hexagon_start_addr =
        static_cast<std::uint32_t>(kProgramBase);
    core_.p_hexagon_num_threads = 1;
    core_.socket.bind(router_.target);
    router_.OutputAt(0).bind(socket);
    router_.OutputAt(1).bind(program_.socket);
    router_.OutputAt(2).bind(doorbell_.accelerator);
    cpu.bind(doorbell_.cpu);
    doorbell_.irq(irq);
    doorbell_.kick(kick_);
    LoadProgram(program);
  }

 private:
  static bool Configure(const std::string& path) {
    cci::cci_broker_handle broker = cci::cci_get_broker();
    const auto set = [&](const std::string& parameter,
                         const cci::cci_value& value) {
      broker.set_preset_cci_value(path + "." + parameter, value);
    };
    set("instance.tcg_mode", cci::cci_value(std::string("COROUTINE")));
    set("instance.sync_policy", cci::cci_value(std::string("tlm2")));
    set("instance.icount", cci::cci_value(true));
    return true;
  }

  // The program goes into program memory the way a debugger would put it
  // there, before the simulation starts.
  void LoadProgram(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("No Hexagon program at " + path);
    const std::vector<std::uint8_t> bytes(std::istreambuf_iterator<char>(file),
                                          {});
    DebugWrite(program_, 0, bytes);
  }

  bool configured_;
  QemuInstanceManager manager_{"manager"};
  QemuInstance instance_;
  hexagon_globalreg global_registers_;
  hexagon_tlb tlb_;
  qemu_cpu_hexagon core_;
  SimpleRouter router_;
  socpuppet::Memory program_;
  Doorbell doorbell_{"doorbell"};
  // Nothing listens to the kick yet: the program polls (firmware/matmul.c).
  sc_core::sc_signal<bool> kick_{"kick"};
};

static_assert(AcceleratorSlot<HexagonNpu>);

}  // namespace spike

#endif  // SPIKES_NPU_HEXAGON_INTEGRATION_HEXAGON_NPU_H_
