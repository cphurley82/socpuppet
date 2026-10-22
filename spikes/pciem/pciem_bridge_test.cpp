// The bridge, with a fake host behind it: what of it can be tried with no
// /dev/pciem.
#include "spikes/pciem/pciem_bridge.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <utility>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"

namespace {

using ::testing::ElementsAre;
using ::testing::IsEmpty;

struct FakeHost : spike::HostSide {
  void Dma(std::uint64_t, std::span<std::uint8_t>, bool) override {}
  void InjectIrq(unsigned vector) override { sent.push_back(vector); }
  std::vector<unsigned> sent;
};

TEST(PciemBridge, MakesTheHostsWritesOnTheFunctionsRegisters) {
  FakeHost host;
  socpuppet::Registry registry = socpuppet::BuiltinComponents();
  spike::AddPciemBridge(registry, "pciem_bridge", host);
  socpuppet::Platform platform(std::move(registry));
  platform.Add("nvme", "behavioral_nvme", {{"blocks", 64}, {"vectors", 2}});
  platform.Add("pciem", "pciem_bridge", {{"vectors", 2}});
  platform.Bind("pciem.bar0", "nvme.bar0");
  platform.Bind("nvme.dma", "pciem.dma");
  platform.Bind("nvme.irq0", "pciem.irq0");
  platform.Bind("nvme.irq1", "pciem.irq1");
  platform.Elaborate();
  auto& bridge = platform.ModuleAt<spike::PciemBridge>("pciem");

  // AQA, then a doorbell the drive refuses: it is not enabled.
  const std::array<spike::HostWrite, 2> writes{
      {{.offset = 0x24, .size = 4, .data = 0x001f'001f},
       {.offset = 0x1000, .size = 8, .data = 1}}};
  bridge.Take(writes);
  platform.TimeToNextActivity();

  std::array<std::byte, 4> aqa{};
  ASSERT_TRUE(platform.DebugRead("pciem.bar0", 0x24, aqa));
  EXPECT_THAT(aqa, ElementsAre(std::byte{0x1f}, std::byte{0}, std::byte{0x1f},
                               std::byte{0}));
  EXPECT_EQ(bridge.Counts().writes, 2U);
  EXPECT_EQ(bridge.Counts().refused_writes, 1U);
  EXPECT_FALSE(bridge.Busy());
  EXPECT_THAT(host.sent, IsEmpty());
}

}  // namespace
