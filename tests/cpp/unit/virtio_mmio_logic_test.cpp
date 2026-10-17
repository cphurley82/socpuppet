#include "socpuppet/core/virtio_mmio_logic.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/memory_store.h"
#include "socpuppet/core/virtio_device.h"
#include "socpuppet/regs/virtio_mmio.h"

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

  std::uint32_t DeviceId() const override { return kId; }
  std::uint64_t Features() const override { return kFeatures; }
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

TEST(WhenTheDriverReadsTheDeviceFeaturesInBothHalves,
     TheyAreWhatTheDeviceOffersWithVersionOneAdded) {
  Rig rig;

  rig.Write32(VIRTIO_MMIO_DEVICE_FEATURES_SEL, 0);
  const std::uint32_t low = rig.Read32(VIRTIO_MMIO_DEVICE_FEATURES);
  rig.Write32(VIRTIO_MMIO_DEVICE_FEATURES_SEL, 1);
  const std::uint32_t high = rig.Read32(VIRTIO_MMIO_DEVICE_FEATURES);

  EXPECT_EQ((std::uint64_t{high} << 32) | low,
            FakeDevice::kFeatures | (std::uint64_t{1} << 32));
}

constexpr std::uint64_t kVersion1 = std::uint64_t{1} << 32;
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

}  // namespace

}  // namespace socpuppet
