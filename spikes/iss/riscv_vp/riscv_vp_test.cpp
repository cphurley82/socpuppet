#include <cstdint>
#include <memory>
#include <utility>
#include <vector>

#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/iss/cpu_slot.h"
#include "spikes/iss/harness/candidate_suite.h"
#include "spikes/iss/harness/virt_board.h"
#include "spikes/iss/riscv_vp/riscv_vp_cpu.h"

namespace spike {

static_assert(CpuSlot<RiscvVpCpu<RiscvVp64>>);
static_assert(CpuSlot<RiscvVpCpu<RiscvVp32>>);

const char* Candidate::Name() { return "riscv-vp"; }
const char* Candidate::Cpu() { return "cpu_riscv_vp"; }

namespace {

template <typename Parts>
socpuppet::Instance Make(const char* name, std::uint64_t reset_pc) {
  auto module = std::make_unique<RiscvVpCpu<Parts>>(name, reset_pc);
  std::vector<socpuppet::Port> ports{
      socpuppet::InitiatorPort("socket", module->socket),
      socpuppet::WireSinkPort("irq", module->irq),
      socpuppet::WireSinkPort("reset", module->reset)};
  return socpuppet::Instance{.module = std::move(module),
                             .ports = std::move(ports)};
}

}  // namespace

socpuppet::Registry Candidate::Components() {
  socpuppet::Registry registry = SpikeComponents();
  registry.Add(Cpu(), [](const char* name, const socpuppet::Config& config) {
    const std::uint64_t reset_pc =
        socpuppet::Required(config, "reset_pc", Cpu());
    return socpuppet::Required(config, "xlen", Cpu()) == 64
               ? Make<RiscvVp64>(name, reset_pc)
               : Make<RiscvVp32>(name, reset_pc);
  });
  return registry;
}

}  // namespace spike
