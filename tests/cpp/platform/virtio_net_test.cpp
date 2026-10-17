#include "socpuppet/models/virtio_net.h"

#include <cstdint>
#include <string>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/virtio_net_logic.h"
#include "tests/cpp/contracts/virtio_device_contract.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/virtio_net_rig.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace {

constexpr std::uint32_t kHeader = socpuppet::VirtioNetLogic::kHeaderBytes;

// What the network device does beyond the contract every virtio device
// keeps: its far end, whoever is at the other end of the wire.
class VirtioNetFarEnd : public VirtioDeviceContract<VirtioNetRig> {
 protected:
  // Has the driver hand the device an empty buffer of `length` bytes on
  // the receive queue, and waits until the device holds it with nothing
  // to put in it.
  void HoldOutABuffer(Driver& driver, std::uint32_t length) {
    driver.SetUp(socpuppet::VirtioNetLogic::kReceiveQueue);
    driver.queue.Describe(0, length, VirtqueueDriver::kWrite);
    driver.queue.MakeAvailable(0);
    driver.Write32(VIRTIO_MMIO_QUEUE_NOTIFY,
                   socpuppet::VirtioNetLogic::kReceiveQueue);
    sc_core::wait(Patience());
    ASSERT_EQ(driver.queue.UsedIndex(), 0);
  }

  socpuppet::VirtioNet& Net() {
    return platform_->ModuleAt<socpuppet::VirtioNet>("device");
  }
};

TEST_F(VirtioNetFarEnd,
       WhenAFrameComesInWhileTheDriverHoldsOutABuffer_ItComesBackWithIt) {
  OnTheBus([this](auto& driver, LineWatcher& line) {
    HoldOutABuffer(driver, 64);

    Net().Send({'s', 'p', 'a', 'm'});

    EXPECT_TRUE(line.WaitForLevel(true, Patience()));
    EXPECT_EQ(driver.queue.UsedIndex(), 1);
    EXPECT_EQ(driver.queue.UsedAt(0).length, kHeader + 4);
    const std::vector<std::uint8_t> written =
        driver.queue.Contents(0, kHeader + 4);
    EXPECT_EQ(std::string(written.begin() + kHeader, written.end()), "spam");
  });
}

TEST_F(VirtioNetFarEnd,
       WhenTheFarEndsSendReturns_TheDeviceHasNotTouchedTheMemoryYet) {
  // Whoever sends may be a script between two runs, outside the
  // simulation, so the frame goes in from a process of the device's own.
  OnTheBus([this](auto& driver, LineWatcher& line) {
    HoldOutABuffer(driver, 64);

    Net().Send({'s', 'p', 'a', 'm'});
    const std::uint16_t as_the_send_returns = driver.queue.UsedIndex();

    EXPECT_EQ(as_the_send_returns, 0);
    EXPECT_TRUE(line.WaitForLevel(true, Patience()));
    EXPECT_EQ(driver.queue.UsedIndex(), 1);
  });
}

}  // namespace
