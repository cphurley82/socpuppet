#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/iss/harness/boot.h"
#include "spikes/iss/harness/virt_board.h"
#include "spikes/iss/inhouse/inhouse_cpu.h"
#include "spikes/iss/vcml_probe/vcml_uart.h"

namespace spike {
namespace {

// The spike's components, a CPU, and VCML's UART.
socpuppet::Registry ComponentsWithVcmlUart() {
  socpuppet::Registry registry = SpikeComponents();
  registry.Add("cpu_inhouse",
               [](const char* name, const socpuppet::Config& config) {
                 auto module = std::make_unique<InhouseCpu<std::uint64_t>>(
                     name, socpuppet::Required(config, "reset_pc", "cpu"));
                 std::vector<socpuppet::Port> ports{
                     socpuppet::InitiatorPort("socket", module->socket),
                     socpuppet::WireSinkPort("irq", module->irq),
                     socpuppet::WireSinkPort("reset", module->reset)};
                 return socpuppet::Instance{.module = std::move(module),
                                            .ports = std::move(ports)};
               });
  registry.Add("vcml_uart", [](const char* name, const socpuppet::Config&) {
    auto module = std::make_unique<VcmlUart>(name);
    std::vector<socpuppet::Port> ports{
        socpuppet::TargetPort("socket", module->socket)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  return registry;
}

}  // namespace

// The probe: does a VCML model work under socpuppet's platform and next
// to a CPU that is not VCML's? Zephyr's own 16550 driver is the judge.
TEST(VcmlUartInTheHarness, CarriesZephyrsGreeting) {
  const std::string image = FirmwarePath("hello_world_qemu_riscv64.bin");
  if (!FileExists(image)) {
    GTEST_SKIP() << image << " is missing. Build it with "
                 << "spikes/iss/firmware/build.sh.";
  }
  SetQuantum(Milliseconds(1));
  socpuppet::Platform platform{ComponentsWithVcmlUart()};
  AddVirtBoard(platform, "board", "cpu_inhouse", {{"reset_pc", kRamBase}},
               Dmi::kOn, "vcml_uart");
  platform.Elaborate();
  Load(platform, "board", ReadFile(image));
  const std::string& output =
      platform.ModuleAt<VcmlUart>("board.uart").Output();

  RunUntil(
      platform,
      [&] { return output.find("Hello World! ") != std::string::npos; },
      Milliseconds(2000));
  platform.Run(Milliseconds(5));

  EXPECT_THAT(output, ::testing::HasSubstr("Hello World! qemu_riscv64"));
}

}  // namespace spike
