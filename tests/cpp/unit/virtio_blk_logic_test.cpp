#include "socpuppet/core/virtio_blk_logic.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/virtqueue.h"
#include "tests/cpp/support/memory_at.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace socpuppet {

namespace {

constexpr std::uint64_t kMemory = 0x8000'0000;
constexpr std::size_t kSector = 512;

// `sectors` sectors, each filled with its own letter from 'a' on, so that
// a sector read from the wrong place shows.
std::vector<std::uint8_t> Lettered(std::size_t sectors) {
  std::vector<std::uint8_t> bytes;
  for (std::size_t sector = 0; sector < sectors; ++sector) {
    bytes.insert(bytes.end(), kSector, static_cast<std::uint8_t>('a' + sector));
  }
  return bytes;
}

// What the device made of a request: the used element's length, the
// status byte, and what it put in the data buffer, if there was one to
// write.
struct Answer {
  std::uint32_t used_length;
  std::uint8_t status;
  std::vector<std::uint8_t> data;
};

// A block device of eight sectors on its one queue, and a driver that
// sends it requests the way EDK2's and Linux's do: a header, the data, and
// a status byte, each in a descriptor of its own.
struct Rig {
  static constexpr Virtqueue::Layout kQueue{.desc = kMemory + 0x1000,
                                            .avail = kMemory + 0x2000,
                                            .used = kMemory + 0x3000,
                                            .size = 16};
  static constexpr std::uint64_t kSectors = 8;

  // Sends a request of `type` at `sector`. `out` is data the device reads
  // (for a write), and `in_length` the bytes of buffer it may write data
  // to (for a read or an identity), before the status byte.
  Answer Ask(std::uint32_t type, std::uint64_t sector,
             std::span<const std::uint8_t> out = {},
             std::uint32_t in_length = 0) {
    std::vector<std::uint8_t> header(16);
    StoreLittleEndian(type, std::span(header).subspan(0, 4));
    StoreLittleEndian(sector, std::span(header).subspan(8, 8));
    // Descriptor 0 is the header and 1 the data, which may run over the
    // buffers of the next few descriptors, so the status is after it.
    const std::uint32_t data_length =
        out.empty() ? in_length : static_cast<std::uint32_t>(out.size());
    const auto status = static_cast<std::uint16_t>(
        2 + data_length / VirtqueueDriver::kBufferStride);
    const bool has_data = data_length > 0;
    driver.Describe(0, 16, VirtqueueDriver::kNext, has_data ? 1 : status);
    driver.Fill(0, header);
    if (!out.empty()) {
      driver.Describe(1, data_length, VirtqueueDriver::kNext, status);
      driver.Fill(1, out);
    } else if (has_data) {
      driver.Describe(1, data_length,
                      VirtqueueDriver::kWrite | VirtqueueDriver::kNext, status);
    }
    driver.Describe(status, 1, VirtqueueDriver::kWrite);
    driver.Fill(status, std::vector<std::uint8_t>{0xEE});
    HandOver();
    return {.used_length = driver.UsedAt(0).length,
            .status = driver.Contents(status, 1)[0],
            .data = in_length > 0 ? driver.Contents(1, in_length)
                                  : std::vector<std::uint8_t>{}};
  }

  // Makes the chain that starts at descriptor 0 available and hands it to
  // the device, as the transport does when the driver rings.
  void HandOver() {
    driver.MakeAvailable(0);
    device.Handle(0, queue.Next().value(), queue);
  }

  MemoryAt memory{kMemory};
  VirtqueueDriver driver{memory, kQueue, kMemory + 0x4000};
  Virtqueue queue{memory, kQueue};
  VirtioBlkLogic device{kSectors};
};

TEST(WhenTheDriverReadsTwoSectors, ItGetsWhatIsThereWithStatusOk) {
  Rig rig;
  rig.device.Load(Lettered(Rig::kSectors));

  const Answer answer = rig.Ask(VirtioBlkLogic::kTypeIn, 3, {}, 2 * kSector);

  EXPECT_EQ(answer.status, VirtioBlkLogic::kStatusOk);
  std::vector<std::uint8_t> expected(kSector, 'd');
  expected.insert(expected.end(), kSector, 'e');
  EXPECT_EQ(answer.data, expected);
  EXPECT_EQ(answer.used_length, 2 * kSector + 1);
}

TEST(WhenTheDriverWritesASector, TheDriveHoldsItThere) {
  Rig rig;
  const std::vector<std::uint8_t> spam(kSector, 's');

  const Answer answer = rig.Ask(VirtioBlkLogic::kTypeOut, 6, spam);

  EXPECT_EQ(answer.status, VirtioBlkLogic::kStatusOk);
  EXPECT_EQ(answer.used_length, 1U);
  std::vector<std::uint8_t> expected(Rig::kSectors * kSector, 0);
  std::ranges::fill(std::span(expected).subspan(6 * kSector, kSector), 's');
  EXPECT_EQ(rig.device.Contents(), expected);
}

TEST(WhenTheDriverReadsPastTheEnd, ItGetsAnIoError) {
  Rig rig;

  const Answer answer = rig.Ask(VirtioBlkLogic::kTypeIn, 7, {}, 2 * kSector);

  EXPECT_EQ(answer.status, VirtioBlkLogic::kStatusIoError);
}

TEST(WhenTheDriverWritesPastTheEnd, ItGetsAnIoErrorAndTheDriveIsUntouched) {
  Rig rig;
  const std::vector<std::uint8_t> spam(2 * kSector, 's');

  const Answer answer = rig.Ask(VirtioBlkLogic::kTypeOut, 7, spam);

  EXPECT_EQ(answer.status, VirtioBlkLogic::kStatusIoError);
  EXPECT_EQ(rig.device.Contents(),
            std::vector<std::uint8_t>(Rig::kSectors * kSector, 0));
}

TEST(WhenTheDriverAsksForTheDrivesIdentity, ItGetsANameInTwentyBytes) {
  Rig rig;

  const Answer answer = rig.Ask(VirtioBlkLogic::kTypeGetId, 0, {}, 20);

  EXPECT_EQ(answer.status, VirtioBlkLogic::kStatusOk);
  const std::string name(answer.data.begin(), answer.data.end());
  EXPECT_EQ(name, std::string("socpuppet").append(11, '\0'));
}

TEST(WhenTheDriverReadsLessThanASector, ItGetsAnIoError) {
  Rig rig;

  const Answer answer = rig.Ask(VirtioBlkLogic::kTypeIn, 0, {}, 100);

  EXPECT_EQ(answer.status, VirtioBlkLogic::kStatusIoError);
}

TEST(WhenTheDriverGivesTheIdentityLessThanTwentyBytes,
     ItGetsAsMuchOfTheNameAsFits) {
  Rig rig;

  const Answer answer = rig.Ask(VirtioBlkLogic::kTypeGetId, 0, {}, 4);

  EXPECT_EQ(answer.status, VirtioBlkLogic::kStatusOk);
  EXPECT_EQ(std::string(answer.data.begin(), answer.data.end()), "socp");
}

TEST(WhenARequestLeavesNoRoomForItsStatus,
     ItComesBackWithNothingWrittenAndTheDriveUntouched) {
  Rig rig;
  std::vector<std::uint8_t> request(16 + kSector, 's');
  StoreLittleEndian(VirtioBlkLogic::kTypeOut, std::span(request).first(4));
  StoreLittleEndian(std::uint32_t{0}, std::span(request).subspan(4, 4));
  StoreLittleEndian(std::uint64_t{0}, std::span(request).subspan(8, 8));
  rig.driver.Describe(0, static_cast<std::uint32_t>(request.size()),
                      VirtqueueDriver::kReadable);
  rig.driver.Fill(0, request);

  rig.HandOver();

  EXPECT_EQ(rig.driver.UsedIndex(), 1);
  EXPECT_EQ(rig.driver.UsedAt(0).length, 0U);
  EXPECT_EQ(rig.device.Contents(),
            std::vector<std::uint8_t>(Rig::kSectors * kSector, 0));
}

TEST(WhenARequestsHeaderIsCutShort, ItComesBackWithNothingWritten) {
  Rig rig;
  rig.driver.Describe(0, 8, VirtqueueDriver::kNext, 1);
  rig.driver.Fill(0, std::vector<std::uint8_t>(8, 0));
  rig.driver.Describe(1, 1, VirtqueueDriver::kWrite);
  rig.driver.Fill(1, std::vector<std::uint8_t>{0xEE});

  rig.HandOver();

  EXPECT_EQ(rig.driver.UsedAt(0).length, 0U);
  EXPECT_EQ(rig.driver.Contents(1, 1)[0], 0xEE);
}

TEST(WhenTheDriverAsksForAFlush, ItIsDoneAtOnce) {
  Rig rig;

  const Answer answer = rig.Ask(VirtioBlkLogic::kTypeFlush, 0);

  EXPECT_EQ(answer.status, VirtioBlkLogic::kStatusOk);
  EXPECT_EQ(answer.used_length, 1U);
}

TEST(WhenTheDriverSendsARequestOfAKindTheDeviceDoesNotKnow,
     ItIsToldItIsUnsupported) {
  Rig rig;
  constexpr std::uint32_t kDiscard = 11;

  const Answer answer = rig.Ask(kDiscard, 0, Lettered(1));

  EXPECT_EQ(answer.status, VirtioBlkLogic::kStatusUnsupported);
}

TEST(WhenTheDriverReadsTheConfiguration, ItFindsTheCapacityInSectors) {
  VirtioBlkLogic device{Rig::kSectors};

  EXPECT_EQ(LoadLittleEndian<std::uint64_t>(device.Config().first(8)),
            Rig::kSectors);
}

TEST(WhenTheDriverWritesTheCapacity, ItIsLeftAsItWas) {
  // The capacity is read-only (section 5.2.4): the disk is as large as it
  // was built.
  VirtioBlkLogic device{Rig::kSectors};
  const std::array<std::uint8_t, 8> huge{0xFF, 0xFF, 0xFF, 0xFF,
                                         0xFF, 0xFF, 0xFF, 0xFF};

  device.WriteConfig(0, huge);

  EXPECT_EQ(LoadLittleEndian<std::uint64_t>(device.Config().first(8)),
            Rig::kSectors);
}

TEST(WhenTheDriverLooksAtTheBlockDevice, ItIsKindTwoWithOneQueueAndFlush) {
  VirtioBlkLogic device{Rig::kSectors};

  EXPECT_EQ(device.DeviceId(), 2U);
  EXPECT_EQ(device.QueueCount(), 1);
  EXPECT_EQ(device.Features(), std::uint64_t{1} << 9);
}

}  // namespace

}  // namespace socpuppet
