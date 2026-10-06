// VCML's endpoint without the adapter's corrections, and VCML's idea of
// which thread the kernel runs on. These tests pass when VCML misbehaves in
// the way docs/pcie-spike.md says it does, so a release that fixes one of
// them turns its test red.
#include <array>
#include <cstddef>
#include <cstdint>
#include <thread>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "spikes/pcie/rig.h"

namespace {

using spike::kCommand;
using spike::kMemoryEnable;
using spike::PciHost;
using spike::Seen;
using spike::StandInRig;
using ::testing::ElementsAre;
using ::testing::Field;

// pci::endpoint sends every access to BAR0 out to the function, so the
// MSI-X table that pci::device keeps in that BAR cannot be reached.
TEST(VcmlAsIs, TheMsixTableInBar0BelongsToTheFunction) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    const std::uint64_t bar0 = host.PlaceBar0(0x10'0000);
    host.SetConfig<std::uint16_t>(kCommand, kMemoryEnable);
    // Vector 0's control word: masked out of reset, if it were the table.
    host.Read(bar0 + 0x2000 + 12);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_ADDRESS_ERROR_RESPONSE);
    EXPECT_THAT(rig.Function().accesses,
                ElementsAre(Field("address", &Seen::address, 0x200CU)));
  });
}

// VCML's models are reset by a pulse on their reset line. Without one, BAR0
// does not yet say that it is a 64-bit memory BAR, and that is the first
// thing Zephyr reads to decide how to size it.
TEST(VcmlAsIs, Bar0DoesNotSayItIs64BitUntilSomethingIsWritten) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    EXPECT_EQ(host.Config(spike::kBar0), 0x0U);
    host.SetConfig<std::uint16_t>(kCommand, 0);
    EXPECT_EQ(host.Config(spike::kBar0), 0x4U);
  });
}

// A debugger's read (debug transport) of a register behind BAR0. A target
// may leave a debug access unanswered, and VCML stops the process when one
// does.
void DebugReadBehindBar0() {
  StandInRig rig;
  std::uint64_t bar0 = 0;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    bar0 = host.BringUp();
  });
  std::array<std::byte, 4> word{};
  rig.Platform().DebugRead("host.driver.socket", bar0, word);
}

TEST(VcmlAsIs, AbortsOnADebugReadTheFunctionDoesNotAnswer) {
  GTEST_FLAG_SET(death_test_style, "threadsafe");
  EXPECT_DEATH(DebugReadBehindBar0(),
               "invalid out-bound transaction response status");
}

// VCML remembers the thread that loaded it and takes that for the thread
// the kernel runs on. From any other, it does not believe that it is inside
// a SystemC process.
TEST(VcmlAsIs, AbortsWhenTheKernelIsNotOnTheThreadThatLoadedIt) {
  GTEST_FLAG_SET(death_test_style, "threadsafe");
  EXPECT_DEATH(
      {
        std::thread kernel{[] {
          StandInRig rig;
          rig.OnTheHost([](BusDriver& bus) {
            PciHost host{bus};
            host.Config(spike::kIds);
          });
        }};
        kernel.join();
      },
      "b_transport outside SC_THREAD");
}

}  // namespace
