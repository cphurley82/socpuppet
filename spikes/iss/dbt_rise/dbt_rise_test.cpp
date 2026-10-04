#include <memory>
#include <utility>
#include <vector>

#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/iss/cpu_slot.h"
#include "spikes/iss/dbt_rise/dbt_rise_cpu.h"
#include "spikes/iss/harness/candidate_suite.h"
#include "spikes/iss/harness/virt_board.h"

namespace spike {

static_assert(CpuSlot<DbtRiseCpu>);

const char* Candidate::Name() { return "DBT-RISE-RISCV"; }
const char* Candidate::Cpu() { return "cpu_dbt_rise"; }

socpuppet::Registry Candidate::Components() {
  socpuppet::Registry registry = SpikeComponents();
  registry.Add(Cpu(), [](const char* name, const socpuppet::Config& config) {
    auto module = std::make_unique<DbtRiseCpu>(
        name, socpuppet::Required(config, "xlen", Cpu()),
        socpuppet::Required(config, "reset_pc", Cpu()));
    std::vector<socpuppet::Port> ports{
        socpuppet::InitiatorPort("socket", module->socket),
        socpuppet::WireSinkPort("irq", module->irq),
        socpuppet::WireSinkPort("reset", module->reset)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  return registry;
}

}  // namespace spike
