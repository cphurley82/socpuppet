#include "socpuppet/core/virtio_console_logic.h"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/memory_store.h"
#include "socpuppet/core/virtqueue.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace socpuppet {

namespace {

// Where the driver's memory is in these tests, 64 KiB of it.
constexpr std::uint64_t kMemory = 0x8000'0000;
constexpr std::size_t kMemorySize = 0x1'0000;

// A memory at some address.
class MemoryAt : public MemoryPort {
 public:
  explicit MemoryAt(std::uint64_t base) : base_(base) {}

  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return address >= base_ && store_.Read(address - base_, out);
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return address >= base_ && store_.Write(address - base_, in);
  }

 private:
  std::uint64_t base_;
  MemoryStore store_{kMemorySize};
};

std::vector<std::uint8_t> Bytes(std::string_view text) {
  return {text.begin(), text.end()};
}

// The console's two queues, each with the driver's side and the device's
// side, and the device itself.
struct Rig {
  static constexpr Virtqueue::Layout kReceive{.desc = kMemory + 0x1000,
                                              .avail = kMemory + 0x2000,
                                              .used = kMemory + 0x3000,
                                              .size = 8};
  static constexpr Virtqueue::Layout kTransmit{.desc = kMemory + 0x5000,
                                               .avail = kMemory + 0x6000,
                                               .used = kMemory + 0x7000,
                                               .size = 8};

  // Hands the device `text` to put out: a readable chain on the transmit
  // queue, as descriptor `index`.
  void Send(std::uint16_t index, std::string_view text) {
    transmit.Describe(index, static_cast<std::uint32_t>(text.size()),
                      VirtqueueDriver::kReadable);
    transmit.Fill(index, Bytes(text));
    transmit.MakeAvailable(index);
    const std::optional<Virtqueue::Chain> chain = transmit_ring.Next();
    ASSERT_TRUE(chain.has_value());
    console.Handle(VirtioConsoleLogic::kTransmitQueue, *chain, transmit_ring);
  }

  // Hands the device an empty buffer of `length` bytes for what comes in:
  // a writable chain on the receive queue, as descriptor `index`, and has
  // it deliver, as the transport does after every hand-over.
  void Offer(std::uint16_t index, std::uint32_t length) {
    receive.Describe(index, length, VirtqueueDriver::kWrite);
    receive.MakeAvailable(index);
    const std::optional<Virtqueue::Chain> chain = receive_ring.Next();
    ASSERT_TRUE(chain.has_value());
    console.Handle(VirtioConsoleLogic::kReceiveQueue, *chain, receive_ring);
    console.Deliver();
  }

  // What the device has put in the buffer of descriptor `index`, as text.
  std::string Received(std::uint16_t index, std::size_t length) {
    const std::vector<std::uint8_t> bytes = receive.Contents(index, length);
    return {bytes.begin(), bytes.end()};
  }

  MemoryAt memory{kMemory};
  VirtqueueDriver receive{memory, kReceive, kMemory + 0x4000};
  VirtqueueDriver transmit{memory, kTransmit, kMemory + 0x8000};
  Virtqueue receive_ring{memory, kReceive};
  Virtqueue transmit_ring{memory, kTransmit};
  VirtioConsoleLogic console;
};

TEST(WhenTheDriverHandsAConsoleBytesToPutOut,
     TheyAreItsOutputAndTheChainComesBackWithNothingWritten) {
  Rig rig;

  rig.Send(0, "spam");
  rig.Send(1, " and eggs");

  EXPECT_EQ(rig.console.Output(), "spam and eggs");
  EXPECT_EQ(rig.transmit.UsedIndex(), 2);
  EXPECT_EQ(rig.transmit.UsedAt(1).length, 0U);
}

TEST(WhenTheDriverHandsAConsoleAnEmptyBufferAndNothingHasComeIn,
     TheDeviceKeepsIt) {
  Rig rig;

  rig.Offer(0, 16);

  EXPECT_EQ(rig.receive.UsedIndex(), 0);
}

TEST(WhenBytesComeInWhileTheDeviceHoldsTwoBuffers,
     DeliveringFillsTheFirstAndPutsTheRestInTheSecond) {
  Rig rig;
  rig.Offer(0, 4);
  rig.Offer(1, 16);

  rig.console.Receive("spam and eggs");
  rig.console.Deliver();

  EXPECT_EQ(rig.receive.UsedIndex(), 2);
  EXPECT_EQ(rig.receive.UsedAt(0).length, 4U);
  EXPECT_EQ(rig.Received(0, 4), "spam");
  EXPECT_EQ(rig.receive.UsedAt(1).length, 9U);
  EXPECT_EQ(rig.Received(1, 9), " and eggs");
}

TEST(WhenBytesHaveComeInBeforeTheDriverHandsAConsoleAnEmptyBuffer,
     TheBufferIsFilledAsItIsHandedOver) {
  Rig rig;
  rig.console.Receive("eggs");

  rig.Offer(0, 16);

  EXPECT_EQ(rig.receive.UsedIndex(), 1);
  EXPECT_EQ(rig.receive.UsedAt(0).length, 4U);
  EXPECT_EQ(rig.Received(0, 4), "eggs");
}

TEST(WhenTheDriverResetsAConsoleThatHoldsABuffer,
     TheBufferIsDroppedAndWhatComesInLaterWaitsForANewOne) {
  Rig rig;
  rig.Offer(0, 16);

  rig.console.Reset();
  rig.console.Receive("spam");
  rig.console.Deliver();
  ASSERT_EQ(rig.receive.UsedIndex(), 0);
  rig.Offer(1, 16);

  EXPECT_EQ(rig.receive.UsedIndex(), 1);
  EXPECT_EQ(rig.receive.UsedAt(0).id, 1U);
  EXPECT_EQ(rig.Received(1, 4), "spam");
  EXPECT_EQ(rig.Received(0, 4), std::string(4, '\0'));
}

}  // namespace

}  // namespace socpuppet
