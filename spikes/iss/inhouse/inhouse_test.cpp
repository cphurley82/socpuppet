#include <cstdint>
#include <memory>
#include <utility>
#include <vector>

#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/iss/cpu_slot.h"
#include "spikes/iss/harness/candidate_suite.h"
#include "spikes/iss/harness/virt_board.h"
#include "spikes/iss/inhouse/inhouse_cpu.h"

namespace spike {

static_assert(CpuSlot<InhouseCpu<std::uint64_t>>);
static_assert(CpuSlot<InhouseCpu<std::uint32_t>>);

const char* Candidate::Name() { return "in-house"; }
const char* Candidate::Cpu() { return "cpu_inhouse"; }

namespace {

template <typename Reg>
socpuppet::Instance Make(const char* name, std::uint64_t reset_pc) {
  auto module = std::make_unique<InhouseCpu<Reg>>(name, reset_pc);
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
               ? Make<std::uint64_t>(name, reset_pc)
               : Make<std::uint32_t>(name, reset_pc);
  });
  return registry;
}

}  // namespace spike
