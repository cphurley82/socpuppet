#include "socpuppet/core/virtio_mmio_logic.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <utility>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/memory_store.h"
#include "socpuppet/core/virtio_device.h"
#include "socpuppet/core/virtqueue.h"
#include "socpuppet/regs/virtio_mmio.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace socpuppet {

namespace {

// Where the driver's memory is in these tests, 64 KiB of it, above 4 GiB so
// that an address in it needs both halves of a queue's address registers.
constexpr std::uint64_t kMemory = 0x1'0000'0000;
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

// A device of no particular kind: enough of one for the transport to have
// something behind it.
class FakeDevice : public VirtioDevice {
 public:
  static constexpr std::uint32_t kId = 0x5A;
  // Two features of its own, by their bits.
  static constexpr std::uint64_t kFeatures = (1U << 1) | (1U << 5);

  static constexpr std::uint16_t kQueues = 2;

  std::uint32_t DeviceId() const override { return kId; }
  std::uint64_t Features() const override { return kFeatures; }
  std::uint16_t QueueCount() const override { return kQueues; }
  void Handle(std::uint16_t queue, Virtqueue::Chain chain,
              Virtqueue& ring) override {
    handled.push_back({queue, chain.head});
    if (uses_each_chain) ring.Used(chain, 0);
  }

  // Which chains the transport has handed over: the queue and the head.
  std::vector<std::pair<std::uint16_t, std::uint16_t>> handled;
  void Reset() override { resets += 1; }
  std::span<std::uint8_t> Config() override { return config; }

  // Its configuration: six bytes of nothing in particular.
  std::array<std::uint8_t, 6> config{0x10, 0x11, 0x12, 0x13, 0x14, 0x15};

  // Whether it gives each chain straight back.
  bool uses_each_chain = false;
  // How many times the transport has reset it.
  int resets = 0;
};

// The transport with the fake behind it, and the driver's way of reaching
// its registers.
struct Rig {
  FakeDevice device;
  MemoryAt memory{kMemory};
  VirtioMmioLogic transport{device, memory};

  bool Write32(std::uint64_t offset, std::uint32_t value) {
    return transport.WriteRegister(offset, LittleEndianBytes(value));
  }
  // Accepts `features`, as the driver does: both halves, through the
  // select register.
  void AcceptFeatures(std::uint64_t features) {
    Write32(VIRTIO_MMIO_DRIVER_FEATURES_SEL, 0);
    Write32(VIRTIO_MMIO_DRIVER_FEATURES, static_cast<std::uint32_t>(features));
    Write32(VIRTIO_MMIO_DRIVER_FEATURES_SEL, 1);
    Write32(VIRTIO_MMIO_DRIVER_FEATURES,
            static_cast<std::uint32_t>(features >> 32));
  }
  // Sets queue `number` up, as the driver does: its size, where its three
  // parts are, and that it is ready.
  void SetUpQueue(std::uint32_t number, Virtqueue::Layout layout) {
    Write32(VIRTIO_MMIO_QUEUE_SEL, number);
    Write32(VIRTIO_MMIO_QUEUE_NUM, layout.size);
    Write32(VIRTIO_MMIO_QUEUE_DESC_LOW,
            static_cast<std::uint32_t>(layout.desc));
    Write32(VIRTIO_MMIO_QUEUE_DESC_HIGH,
            static_cast<std::uint32_t>(layout.desc >> 32));
    Write32(VIRTIO_MMIO_QUEUE_DRIVER_LOW,
            static_cast<std::uint32_t>(layout.avail));
    Write32(VIRTIO_MMIO_QUEUE_DRIVER_HIGH,
            static_cast<std::uint32_t>(layout.avail >> 32));
    Write32(VIRTIO_MMIO_QUEUE_DEVICE_LOW,
            static_cast<std::uint32_t>(layout.used));
    Write32(VIRTIO_MMIO_QUEUE_DEVICE_HIGH,
            static_cast<std::uint32_t>(layout.used >> 32));
    Write32(VIRTIO_MMIO_QUEUE_READY, VIRTIO_MMIO_QUEUE_READY_READY);
  }
  // The bytes do not start out as zeros, so that a register the transport
  // leaves untouched is not taken for one that reads as zero.
  std::uint32_t Read32(std::uint64_t offset) const {
    std::array<std::uint8_t, 4> bytes{0xA5, 0xA5, 0xA5, 0xA5};
    EXPECT_TRUE(transport.ReadRegister(offset, bytes));
    return LoadLittleEndian<std::uint32_t>(bytes);
  }
};

TEST(WhenTheDriverReadsTheFirstFourRegistersOfAVirtioDevice,
     TheySayVirtioVersionTwoWhatTheDeviceIsAndWhoMadeIt) {
  const Rig rig;

  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_MAGIC_VALUE),
            VIRTIO_MMIO_MAGIC_VALUE_AT_RESET);
  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_VERSION), VIRTIO_MMIO_VERSION_AT_RESET);
  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_DEVICE_ID), FakeDevice::kId);
  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_VENDOR_ID), 0x5350U);
}

// The transport's own feature bit: the modern layout (virtio 1.2, section 6).
constexpr std::uint64_t kVersion1 = std::uint64_t{1} << 32;

TEST(WhenTheDriverReadsTheDeviceFeaturesInBothHalves,
     TheyAreWhatTheDeviceOffersWithVersionOneAdded) {
  Rig rig;

  rig.Write32(VIRTIO_MMIO_DEVICE_FEATURES_SEL, 0);
  const std::uint32_t low = rig.Read32(VIRTIO_MMIO_DEVICE_FEATURES);
  rig.Write32(VIRTIO_MMIO_DEVICE_FEATURES_SEL, 1);
  const std::uint32_t high = rig.Read32(VIRTIO_MMIO_DEVICE_FEATURES);

  EXPECT_EQ((std::uint64_t{high} << 32) | low,
            FakeDevice::kFeatures | kVersion1);
}

// The spec has the driver only write its features, but Zephyr's transport
// reads a half back to set one bit of it, as QEMU's device allows.
TEST(WhenTheDriverReadsBackTheFeaturesItAccepted, ItGetsTheHalfItSelected) {
  Rig rig;
  rig.AcceptFeatures((std::uint64_t{0x5555'0000} << 32) | 0x0000'AAAA);

  rig.Write32(VIRTIO_MMIO_DRIVER_FEATURES_SEL, 0);
  const std::uint32_t low = rig.Read32(VIRTIO_MMIO_DRIVER_FEATURES);
  rig.Write32(VIRTIO_MMIO_DRIVER_FEATURES_SEL, 1);
  const std::uint32_t high = rig.Read32(VIRTIO_MMIO_DRIVER_FEATURES);

  EXPECT_EQ(low, 0x0000'AAAAU);
  EXPECT_EQ(high, 0x5555'0000U);
}

constexpr std::uint32_t kSeenAndDriven =
    VIRTIO_MMIO_STATUS_ACKNOWLEDGE | VIRTIO_MMIO_STATUS_DRIVER;

TEST(WhenTheDriverAcceptsWhatWasOfferedAndVersionOneAndSaysFeaturesOk,
     TheTransportKeepsFeaturesOk) {
  Rig rig;
  rig.AcceptFeatures(FakeDevice::kFeatures | kVersion1);

  rig.Write32(VIRTIO_MMIO_STATUS,
              kSeenAndDriven | VIRTIO_MMIO_STATUS_FEATURES_OK);

  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_STATUS),
            kSeenAndDriven | VIRTIO_MMIO_STATUS_FEATURES_OK);
}

TEST(WhenTheDriverAcceptsAFeatureThatWasNotOfferedAndSaysFeaturesOk,
     TheTransportDoesNotKeepFeaturesOk) {
  Rig rig;
  rig.AcceptFeatures(FakeDevice::kFeatures | (1U << 7) | kVersion1);

  rig.Write32(VIRTIO_MMIO_STATUS,
              kSeenAndDriven | VIRTIO_MMIO_STATUS_FEATURES_OK);

  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_STATUS), kSeenAndDriven);
}

TEST(WhenTheDriverLeavesVersionOneOutOfWhatItAcceptsAndSaysFeaturesOk,
     TheTransportDoesNotKeepFeaturesOk) {
  Rig rig;
  rig.AcceptFeatures(FakeDevice::kFeatures);

  rig.Write32(VIRTIO_MMIO_STATUS,
              kSeenAndDriven | VIRTIO_MMIO_STATUS_FEATURES_OK);

  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_STATUS), kSeenAndDriven);
}

TEST(WhenTheDriverAsksHowBigAQueueCanBe,
     TheAnswerIsTheMostForAQueueTheDeviceHasAndZeroForOneItHasNot) {
  Rig rig;

  rig.Write32(VIRTIO_MMIO_QUEUE_SEL, FakeDevice::kQueues - 1);
  const std::uint32_t last = rig.Read32(VIRTIO_MMIO_QUEUE_NUM_MAX);
  rig.Write32(VIRTIO_MMIO_QUEUE_SEL, FakeDevice::kQueues);
  const std::uint32_t beyond = rig.Read32(VIRTIO_MMIO_QUEUE_NUM_MAX);

  EXPECT_EQ(last, VirtioMmioLogic::kQueueSizeMax);
  EXPECT_EQ(beyond, 0U);
}

// A queue of eight entries, laid out in the memory the way the
// specification lays it out, and its buffers after it.
constexpr Virtqueue::Layout kQueue{.desc = kMemory + 0x1000,
                                   .avail = kMemory + 0x2000,
                                   .used = kMemory + 0x3000,
                                   .size = 8};
constexpr std::uint64_t kBuffers = kMemory + 0x4000;

TEST(WhenTheDriverHasSetOneQueueUp,
     ThatQueueReadsAsReadyAndTheDevicesOtherQueueDoesNot) {
  Rig rig;
  rig.SetUpQueue(1, kQueue);

  rig.Write32(VIRTIO_MMIO_QUEUE_SEL, 1);
  const std::uint32_t set_up = rig.Read32(VIRTIO_MMIO_QUEUE_READY);
  rig.Write32(VIRTIO_MMIO_QUEUE_SEL, 0);
  const std::uint32_t other = rig.Read32(VIRTIO_MMIO_QUEUE_READY);

  EXPECT_EQ(set_up, VIRTIO_MMIO_QUEUE_READY_READY);
  EXPECT_EQ(other, 0U);
}

TEST(WhenTheDriverGivesAQueueMoreEntriesThanItMayHave, TheWriteIsRefused) {
  Rig rig;
  rig.Write32(VIRTIO_MMIO_QUEUE_SEL, 0);

  EXPECT_FALSE(
      rig.Write32(VIRTIO_MMIO_QUEUE_NUM, VirtioMmioLogic::kQueueSizeMax * 2));
}

TEST(WhenTheDriverRingsTheDoorbellOfAQueueWithTwoChainsAvailable,
     TheDeviceIsHandedBothInOrder) {
  Rig rig;
  VirtqueueDriver driver{rig.memory, kQueue, kBuffers};
  rig.SetUpQueue(0, kQueue);
  driver.Describe(0, 8, VirtqueueDriver::kReadable);
  driver.Describe(1, 8, VirtqueueDriver::kReadable);
  driver.MakeAvailable(0);
  driver.MakeAvailable(1);

  rig.Write32(VIRTIO_MMIO_QUEUE_NOTIFY, 0);
  rig.transport.CarryOut();

  const std::vector<std::pair<std::uint16_t, std::uint16_t>> both = {{0, 0},
                                                                     {0, 1}};
  EXPECT_EQ(rig.device.handled, both);
}

TEST(WhenTheDeviceHasUsedAChain, TheTransportInterruptsAndSaysWhy) {
  Rig rig;
  VirtqueueDriver driver{rig.memory, kQueue, kBuffers};
  rig.SetUpQueue(0, kQueue);
  rig.device.uses_each_chain = true;
  driver.Describe(0, 8, VirtqueueDriver::kReadable);
  driver.MakeAvailable(0);

  rig.Write32(VIRTIO_MMIO_QUEUE_NOTIFY, 0);
  rig.transport.CarryOut();

  EXPECT_TRUE(rig.transport.Interrupting());
  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_INTERRUPT_STATUS),
            VIRTIO_MMIO_INTERRUPT_STATUS_USED_BUFFER);
}

TEST(WhenTheDriverAcknowledgesTheUsedBufferInterrupt,
     TheTransportStopsInterruptingUntilTheNextChainIsUsed) {
  Rig rig;
  VirtqueueDriver driver{rig.memory, kQueue, kBuffers};
  rig.SetUpQueue(0, kQueue);
  rig.device.uses_each_chain = true;
  driver.Describe(0, 8, VirtqueueDriver::kReadable);
  driver.Describe(1, 8, VirtqueueDriver::kReadable);
  driver.MakeAvailable(0);
  rig.Write32(VIRTIO_MMIO_QUEUE_NOTIFY, 0);
  rig.transport.CarryOut();

  rig.Write32(VIRTIO_MMIO_INTERRUPT_ACK, VIRTIO_MMIO_INTERRUPT_ACK_USED_BUFFER);
  const bool after_the_ack = rig.transport.Interrupting();
  driver.MakeAvailable(1);
  rig.Write32(VIRTIO_MMIO_QUEUE_NOTIFY, 0);
  rig.transport.CarryOut();

  EXPECT_FALSE(after_the_ack);
  EXPECT_TRUE(rig.transport.Interrupting());
}

TEST(WhenTheDriverWritesZeroToStatus,
     TheDeviceIsResetAndItsQueuesFeaturesAndInterruptAreForgotten) {
  Rig rig;
  VirtqueueDriver driver{rig.memory, kQueue, kBuffers};
  rig.AcceptFeatures(FakeDevice::kFeatures | kVersion1);
  rig.Write32(VIRTIO_MMIO_STATUS,
              kSeenAndDriven | VIRTIO_MMIO_STATUS_FEATURES_OK);
  rig.SetUpQueue(0, kQueue);
  rig.device.uses_each_chain = true;
  driver.Describe(0, 8, VirtqueueDriver::kReadable);
  driver.MakeAvailable(0);
  rig.Write32(VIRTIO_MMIO_QUEUE_NOTIFY, 0);
  rig.transport.CarryOut();

  rig.Write32(VIRTIO_MMIO_STATUS, 0);

  EXPECT_EQ(rig.device.resets, 1);
  EXPECT_FALSE(rig.transport.Interrupting());
  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_STATUS), 0U);
  rig.Write32(VIRTIO_MMIO_QUEUE_SEL, 0);
  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_QUEUE_READY), 0U);
  // The driver's features are gone too: FEATURES_OK alone, with nothing
  // accepted, is not kept.
  rig.Write32(VIRTIO_MMIO_STATUS,
              kSeenAndDriven | VIRTIO_MMIO_STATUS_FEATURES_OK);
  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_STATUS), kSeenAndDriven);
}

TEST(WhenTheDriverReadsTheDevicesConfigurationTwoBytesAtATime,
     ItGetsTheDevicesBytes) {
  Rig rig;
  std::array<std::uint8_t, 2> two{};

  ASSERT_TRUE(rig.transport.ReadRegister(VIRTIO_MMIO_CONFIG + 4, two));

  EXPECT_EQ(two, (std::array<std::uint8_t, 2>{0x14, 0x15}));
}

TEST(WhenTheDriverWritesOneByteOfTheDevicesConfiguration, TheDeviceHasIt) {
  Rig rig;
  const std::array<std::uint8_t, 1> one{0x99};

  ASSERT_TRUE(rig.transport.WriteRegister(VIRTIO_MMIO_CONFIG + 1, one));

  EXPECT_EQ(rig.device.config[1], 0x99);
}

TEST(WhenTheDriverReadsPastTheEndOfTheDevicesConfiguration, TheReadIsRefused) {
  Rig rig;
  std::array<std::uint8_t, 4> four{};

  EXPECT_FALSE(rig.transport.ReadRegister(VIRTIO_MMIO_CONFIG + 4, four));
}

TEST(WhenAnAccessToATransportRegisterIsNotOneWholeAlignedWord, ItIsRefused) {
  Rig rig;
  std::array<std::uint8_t, 2> two{};
  std::array<std::uint8_t, 4> four{};

  EXPECT_FALSE(rig.transport.ReadRegister(VIRTIO_MMIO_MAGIC_VALUE, two));
  EXPECT_FALSE(rig.transport.ReadRegister(VIRTIO_MMIO_MAGIC_VALUE + 2, four));
  EXPECT_FALSE(rig.transport.WriteRegister(VIRTIO_MMIO_QUEUE_SEL, two));
}

TEST(WhenTheDriverAsksAboutSharedMemory, TheLengthSaysThereIsNone) {
  Rig rig;
  EXPECT_TRUE(rig.Write32(VIRTIO_MMIO_SHM_SEL, 0));

  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_SHM_LEN_LOW),
            VIRTIO_MMIO_SHM_LEN_LOW_AT_RESET);
  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_SHM_LEN_HIGH),
            VIRTIO_MMIO_SHM_LEN_HIGH_AT_RESET);
}

TEST(WhenTheDriverSelectsAHalfOfTheFeaturesThatThereIsNot,
     ItReadsAsZeroAndWhatIsWrittenThereCountsForNothing) {
  Rig rig;
  rig.AcceptFeatures(FakeDevice::kFeatures | kVersion1);
  rig.Write32(VIRTIO_MMIO_DRIVER_FEATURES_SEL, 2);
  rig.Write32(VIRTIO_MMIO_DRIVER_FEATURES, 0xFFFF'FFFF);
  rig.Write32(VIRTIO_MMIO_DEVICE_FEATURES_SEL, 2);

  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_DEVICE_FEATURES), 0U);
  rig.Write32(VIRTIO_MMIO_STATUS,
              kSeenAndDriven | VIRTIO_MMIO_STATUS_FEATURES_OK);
  EXPECT_EQ(rig.Read32(VIRTIO_MMIO_STATUS),
            kSeenAndDriven | VIRTIO_MMIO_STATUS_FEATURES_OK);
}

TEST(WhenTheDriverRingsTheDoorbellOfAQueueItHasNotSetUp, TheWriteIsRefused) {
  Rig rig;

  EXPECT_FALSE(rig.Write32(VIRTIO_MMIO_QUEUE_NOTIFY, 0));
}

}  // namespace

}  // namespace socpuppet
