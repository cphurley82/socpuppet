#include "socpuppet/models/virtio_console.h"

#include <cstdint>
#include <string>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/virtio_console_logic.h"
#include "tests/cpp/contracts/virtio_device_contract.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/virtio_console_rig.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace {

// What the console does beyond the contract every virtio device keeps: its
// far end, whoever sits at the other end of the serial line.
class VirtioConsoleFarEnd : public VirtioDeviceContract<VirtioConsoleRig> {
 protected:
  // Has the driver hand the device an empty buffer of `length` bytes on
  // the receive queue, and waits until the device holds it with nothing
  // to put in it.
  void HoldOutABuffer(Driver& driver, std::uint32_t length) {
    driver.SetUp(socpuppet::VirtioConsoleLogic::kReceiveQueue);
    driver.queue.Describe(0, length, VirtqueueDriver::kWrite);
    driver.queue.MakeAvailable(0);
    driver.Write32(VIRTIO_MMIO_QUEUE_NOTIFY,
                   socpuppet::VirtioConsoleLogic::kReceiveQueue);
    sc_core::wait(Patience());
    ASSERT_EQ(driver.queue.UsedIndex(), 0);
  }

  socpuppet::VirtioConsole& Console() {
    return platform_->ModuleAt<socpuppet::VirtioConsole>("device");
  }
};

TEST_F(VirtioConsoleFarEnd,
       WhenTheFarEndTypesWhileTheDriverHoldsOutABuffer_ItComesBackWithThat) {
  OnTheBus([this](auto& driver, LineWatcher& line) {
    HoldOutABuffer(driver, 16);

    Console().Write("spam");

    EXPECT_TRUE(line.WaitForLevel(true, Patience()));
    EXPECT_EQ(driver.queue.UsedIndex(), 1);
    EXPECT_EQ(driver.queue.UsedAt(0).length, 4U);
    const std::vector<std::uint8_t> typed = driver.queue.Contents(0, 4);
    EXPECT_EQ(std::string(typed.begin(), typed.end()), "spam");
  });
}

TEST_F(VirtioConsoleFarEnd,
       WhenTheFarEndsWriteReturns_TheDeviceHasNotTouchedTheMemoryYet) {
  // Whoever types may be a script between two runs, outside the
  // simulation, so the bytes go in from a process of the device's own.
  OnTheBus([this](auto& driver, LineWatcher& line) {
    HoldOutABuffer(driver, 16);

    Console().Write("spam");
    const std::uint16_t as_the_write_returns = driver.queue.UsedIndex();

    EXPECT_EQ(as_the_write_returns, 0);
    EXPECT_TRUE(line.WaitForLevel(true, Patience()));
    EXPECT_EQ(driver.queue.UsedIndex(), 1);
  });
}

}  // namespace
