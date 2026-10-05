#include <memory>
#include <utility>
#include <vector>

#include <cciutils.h>
#include <gtest/gtest.h>
#include <scp/report.h>

#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/iss/qbox/cpu_slot.h"
#include "spikes/iss/qbox/harness/candidate_suite.h"
#include "spikes/iss/qbox/harness/virt_board.h"
#include "spikes/iss/qbox/integration/qbox_cpu.h"

namespace spike {

static_assert(CpuSlot<QboxCpu>);

const char* Candidate::Name() { return "QBox"; }
const char* Candidate::Cpu() { return "cpu_qbox"; }

socpuppet::Registry Candidate::Components() {
  socpuppet::Registry registry = SpikeComponents();
  registry.Add(Cpu(), [](const char* name, const socpuppet::Config& config) {
    auto module = std::make_unique<QboxCpu>(
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

// QBox's SystemC is a shared library, and the main() inside it refers to
// sc_main() whether or not that main() is used. This satisfies the linker.
int sc_main(int, char**) { return 0; }

// A main() of our own, because QBox's parameters need their broker to exist
// before any component does.
int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  scp::init_logging(scp::LogConfig().logLevel(scp::log::WARNING));
  gs::ConfigurableBroker broker{};
  return RUN_ALL_TESTS();
}
