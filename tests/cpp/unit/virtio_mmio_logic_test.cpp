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

  std::uint32_t DeviceId() const override { return kId; }
};

// The transport with the fake behind it, and the driver's way of reaching
// its registers.
struct Rig {
  FakeDevice device;
  MemoryAt memory{kMemory};
  VirtioMmioLogic transport{device, memory};

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

}  // namespace

}  // namespace socpuppet
