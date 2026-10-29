#include "socpuppet/core/virtio_net_logic.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/virtqueue.h"
#include "tests/cpp/support/memory_at.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace socpuppet {

namespace {

constexpr std::uint64_t kMemory = 0x8000'0000;
// The header in front of every frame, both ways (section 5.1.6): twelve
// bytes, the last two of which say how many buffers the frame took.
constexpr std::size_t kHeader = 12;

std::vector<std::uint8_t> Bytes(std::string_view text) {
  return {text.begin(), text.end()};
}

std::string Text(const std::vector<std::uint8_t>& bytes) {
  return {bytes.begin(), bytes.end()};
}

// A header as a driver sends it with a frame: all zeros.
std::vector<std::uint8_t> WithAHeader(std::string_view frame) {
  std::vector<std::uint8_t> bytes(kHeader, 0);
  bytes.insert(bytes.end(), frame.begin(), frame.end());
  return bytes;
}

// The network device's two queues, with the driver's side and the
// device's side of each, and the device, whose address is
// 02:00:5e:00:53:01.
struct Rig {
  static constexpr Virtqueue::Layout kReceive{
      .desc = kMemory + 0x1000,
      .avail = kMemory + 0x2000,
      .used = kMemory + 0x3000,
      .size = 8,
  };
  static constexpr Virtqueue::Layout kTransmit{
      .desc = kMemory + 0x5000,
      .avail = kMemory + 0x6000,
      .used = kMemory + 0x7000,
      .size = 8,
  };
  static constexpr std::uint64_t kMac = 0x0200'5E00'5301;

  // Has the driver send `frame` with its header in one buffer, as
  // Zephyr's driver does, as descriptor `index`.
  void Transmit(std::uint16_t index, std::string_view frame) {
    const std::vector<std::uint8_t> bytes = WithAHeader(frame);
    transmit.Describe(index, static_cast<std::uint32_t>(bytes.size()),
                      VirtqueueDriver::kReadable);
    transmit.Fill(index, bytes);
    HandOver(transmit, transmit_ring, index, VirtioNetLogic::kTransmitQueue);
  }

  // Hands the device an empty buffer of `length` bytes, header and frame
  // together, as Zephyr's driver does, as descriptor `index`, and has it
  // deliver, as the transport does after every hand-over.
  void Offer(std::uint16_t index, std::uint32_t length) {
    receive.Describe(index, length, VirtqueueDriver::kWrite);
    HandOver(receive, receive_ring, index, VirtioNetLogic::kReceiveQueue);
    net.Deliver();
  }

  void HandOver(VirtqueueDriver& driver, Virtqueue& ring, std::uint16_t head,
                std::uint16_t queue) {
    driver.MakeAvailable(head);
    net.Handle(queue, NextChain(ring), ring);
  }

  MemoryAt memory{kMemory};
  VirtqueueDriver receive{memory, kReceive, kMemory + 0x4000};
  VirtqueueDriver transmit{memory, kTransmit, kMemory + 0x8000};
  Virtqueue receive_ring{memory, kReceive};
  Virtqueue transmit_ring{memory, kTransmit};
  VirtioNetLogic net{kMac};
};

TEST(WhenTheDriverSendsTwoFrames, TheyGoOnTheWireWithoutTheirHeaders) {
  Rig rig;

  rig.Transmit(0, "spam");
  rig.Transmit(1, "eggs");

  ASSERT_EQ(rig.net.Transmitted().size(), 2U);
  EXPECT_EQ(Text(rig.net.Transmitted()[0]), "spam");
  EXPECT_EQ(Text(rig.net.Transmitted()[1]), "eggs");
}

TEST(WhenTheDriverSendsAFrame, ItsBufferComesBackWithNothingWritten) {
  Rig rig;

  rig.Transmit(0, "spam");

  ASSERT_EQ(rig.transmit.UsedIndex(), 1);
  EXPECT_EQ(rig.transmit.UsedAt(0).length, 0U);
}

TEST(WhenTheDriverSendsAChainShorterThanAHeader,
     ItComesBackAndNothingGoesOnTheWire) {
  Rig rig;
  rig.transmit.Describe(0, 4, VirtqueueDriver::kReadable);
  rig.transmit.Fill(0, Bytes("spam"));

  rig.HandOver(rig.transmit, rig.transmit_ring, 0,
               VirtioNetLogic::kTransmitQueue);

  EXPECT_EQ(rig.transmit.UsedIndex(), 1);
  EXPECT_TRUE(rig.net.Transmitted().empty());
}

TEST(WhenTheDriverSendsAFrameWithItsHeaderInADescriptorOfItsOwn,
     TheFrameGoesOnTheWireWhole) {
  // EDK2's driver puts the header in one descriptor and the frame in the
  // next.
  Rig rig;
  rig.transmit.Describe(0, kHeader, VirtqueueDriver::kNext, 1);
  rig.transmit.Fill(0, std::vector<std::uint8_t>(kHeader, 0));
  rig.transmit.Describe(1, 4, VirtqueueDriver::kReadable);
  rig.transmit.Fill(1, Bytes("spam"));

  rig.HandOver(rig.transmit, rig.transmit_ring, 0,
               VirtioNetLogic::kTransmitQueue);

  ASSERT_EQ(rig.net.Transmitted().size(), 1U);
  EXPECT_EQ(Text(rig.net.Transmitted()[0]), "spam");
}

TEST(WhenAFrameComesInWhileTheDriverHoldsOutABuffer,
     ItIsWrittenAfterAHeaderThatSaysItTookOneBuffer) {
  Rig rig;
  rig.Offer(0, 64);

  rig.net.Receive(Bytes("spam and eggs"));
  rig.net.Deliver();

  ASSERT_EQ(rig.receive.UsedIndex(), 1);
  EXPECT_EQ(rig.receive.UsedAt(0).length, kHeader + 13);
  std::vector<std::uint8_t> header(kHeader, 0);
  header[10] = 1;  // num_buffers, little-endian
  const std::vector<std::uint8_t> written =
      rig.receive.Contents(0, kHeader + 13);
  EXPECT_EQ(std::vector(written.begin(), written.begin() + kHeader), header);
  EXPECT_EQ(Text({written.begin() + kHeader, written.end()}), "spam and eggs");
}

TEST(WhenAFrameComesInBeforeTheDriverHoldsOutABuffer,
     ItIsWrittenAsTheBufferIsHandedOver) {
  Rig rig;
  rig.net.Receive(Bytes("eggs"));

  rig.Offer(0, 64);

  ASSERT_EQ(rig.receive.UsedIndex(), 1);
  EXPECT_EQ(Text(rig.receive.Contents(0, kHeader + 4)).substr(kHeader), "eggs");
}

TEST(WhenAFrameComesInIntoABufferInTwoParts,
     TheHeaderFillsTheFirstAndTheFrameTheSecond) {
  // EDK2's driver hands over each receive buffer as a header's descriptor
  // and a frame's.
  Rig rig;
  rig.receive.Describe(0, kHeader,
                       VirtqueueDriver::kWrite | VirtqueueDriver::kNext, 1);
  rig.receive.Describe(1, 64, VirtqueueDriver::kWrite);
  rig.HandOver(rig.receive, rig.receive_ring, 0, VirtioNetLogic::kReceiveQueue);

  rig.net.Receive(Bytes("spam"));
  rig.net.Deliver();

  std::vector<std::uint8_t> header(kHeader, 0);
  header[10] = 1;  // num_buffers, little-endian
  EXPECT_EQ(rig.receive.Contents(0, kHeader), header);
  EXPECT_EQ(Text(rig.receive.Contents(1, 4)), "spam");
  EXPECT_EQ(rig.receive.UsedAt(0).length, kHeader + 4);
}

TEST(WhenAFrameComesInThatIsLongerThanTheBufferHeldOut,
     ItIsDroppedAndCountedAndTheBufferWaitsForTheNext) {
  Rig rig;
  rig.Offer(0, kHeader + 4);

  rig.net.Receive(Bytes("spam and eggs"));
  rig.net.Receive(Bytes("spam"));
  rig.net.Deliver();

  EXPECT_EQ(rig.net.Dropped(), 1U);
  ASSERT_EQ(rig.receive.UsedIndex(), 1);
  EXPECT_EQ(Text(rig.receive.Contents(0, kHeader + 4)).substr(kHeader), "spam");
}

TEST(WhenTheDriverResetsANetworkDeviceThatHoldsABuffer,
     TheBufferIsDroppedAndAFrameWaitsForANewOne) {
  Rig rig;
  rig.Offer(0, 64);

  rig.net.Reset();
  rig.net.Receive(Bytes("spam"));
  rig.net.Deliver();
  ASSERT_EQ(rig.receive.UsedIndex(), 0);
  rig.Offer(1, 64);

  EXPECT_EQ(rig.receive.UsedAt(0).id, 1U);
}

TEST(WhenTheDriverReadsTheConfiguration, ItFindsTheMacAddressFirstByteFirst) {
  VirtioNetLogic net{Rig::kMac};

  const std::span<const std::uint8_t> config = net.Config();

  EXPECT_EQ(std::vector(config.begin(), config.begin() + 6),
            (std::vector<std::uint8_t>{0x02, 0x00, 0x5E, 0x00, 0x53, 0x01}));
}

TEST(WhenTheDriverLooksAtTheNetworkDevice,
     ItIsKindOneWithTwoQueuesAndOffersItsMacAddress) {
  VirtioNetLogic net{Rig::kMac};

  EXPECT_EQ(net.DeviceId(), 1U);
  EXPECT_EQ(net.QueueCount(), 2);
  EXPECT_EQ(net.Features(), std::uint64_t{1} << 5U);
}

}  // namespace

}  // namespace socpuppet
