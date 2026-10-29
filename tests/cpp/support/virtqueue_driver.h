#ifndef TESTS_CPP_SUPPORT_VIRTQUEUE_DRIVER_H_
#define TESTS_CPP_SUPPORT_VIRTQUEUE_DRIVER_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <utility>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/virtqueue.h"

// The driver's side of a split virtqueue, for tests of the device's side:
// it writes descriptors and the available ring into a memory the way the
// specification lays them out (virtio 1.2, section 2.7), and reads the
// used ring back. Buffer `index` is at `buffers + kBufferStride * index`.
class VirtqueueDriver {
 public:
  // Descriptor flags, section 2.7.5: a descriptor with neither is one the
  // device reads.
  static constexpr std::uint16_t kReadable = 0;
  static constexpr std::uint16_t kNext = 1;
  static constexpr std::uint16_t kWrite = 2;
  // How far apart the buffers of two neighbouring descriptors are.
  static constexpr std::uint64_t kBufferStride = 0x100;

  // One element of the used ring: which chain, and how many bytes the
  // device wrote to it.
  struct Used {
    std::uint32_t id;
    std::uint32_t length;
  };

  VirtqueueDriver(socpuppet::MemoryPort& memory,
                  socpuppet::Virtqueue::Layout layout, std::uint64_t buffers)
      : memory_(memory), layout_(layout), buffers_(buffers) {}

  // Describes buffer `index`: `length` bytes at its address, with `flags`,
  // chained to descriptor `chained_to` if the flags say so. Gives the
  // address.
  std::uint64_t Describe(std::uint16_t index, std::uint32_t length,
                         std::uint16_t flags, std::uint16_t chained_to = 0) {
    const std::uint64_t address = BufferAt(index);
    std::array<std::uint8_t, 16> descriptor{};
    const std::span<std::uint8_t> bytes = descriptor;
    socpuppet::StoreLittleEndian(address, bytes.subspan(0, 8));
    socpuppet::StoreLittleEndian(length, bytes.subspan(8, 4));
    socpuppet::StoreLittleEndian(flags, bytes.subspan(12, 2));
    socpuppet::StoreLittleEndian(chained_to, bytes.subspan(14, 2));
    EXPECT_TRUE(
        memory_.Write(layout_.desc + (std::uint64_t{16} * index), descriptor));
    return address;
  }

  // Fills the buffer of descriptor `index` with `bytes`.
  void Fill(std::uint16_t index, std::span<const std::uint8_t> bytes) {
    EXPECT_TRUE(memory_.Write(BufferAt(index), bytes));
  }

  // What the buffer of descriptor `index` holds, `length` bytes of it.
  std::vector<std::uint8_t> Contents(std::uint16_t index, std::size_t length) {
    std::vector<std::uint8_t> data(length);
    EXPECT_TRUE(memory_.Read(BufferAt(index), data));
    return data;
  }

  // Puts the chain that starts at descriptor `head` in the available ring
  // and moves the ring's index on.
  void MakeAvailable(std::uint16_t head) {
    EXPECT_TRUE(memory_.Write(
        layout_.avail + 4 + (std::uint64_t{2} * (available_ % layout_.size)),
        socpuppet::LittleEndianBytes(head)));
    ++available_;
    EXPECT_TRUE(memory_.Write(layout_.avail + 2,
                              socpuppet::LittleEndianBytes(available_)));
  }

  // What the used ring says: its index, and the element at `slot`.
  std::uint16_t UsedIndex() { return Load16(layout_.used + 2); }
  Used UsedAt(std::uint16_t slot) {
    std::array<std::uint8_t, 8> bytes{};
    EXPECT_TRUE(
        memory_.Read(layout_.used + 4 + (std::uint64_t{8} * slot), bytes));
    const std::span<const std::uint8_t> fields = bytes;
    return {
        .id = socpuppet::LoadLittleEndian<std::uint32_t>(fields.subspan(0, 4)),
        .length =
            socpuppet::LoadLittleEndian<std::uint32_t>(fields.subspan(4, 4)),
    };
  }

 private:
  std::uint64_t BufferAt(std::uint16_t index) const {
    return buffers_ + (kBufferStride * index);
  }
  std::uint16_t Load16(std::uint64_t address) {
    std::array<std::uint8_t, 2> bytes{};
    EXPECT_TRUE(memory_.Read(address, bytes));
    return socpuppet::LoadLittleEndian<std::uint16_t>(bytes);
  }

  socpuppet::MemoryPort& memory_;
  socpuppet::Virtqueue::Layout layout_;
  std::uint64_t buffers_;
  std::uint16_t available_ = 0;
};

// The next chain the driver has made available on `ring`, which the test
// expects there to be. If there is none the test fails, and an empty chain
// stands in so that it can go on to say what else went wrong.
inline socpuppet::Virtqueue::Chain NextChain(socpuppet::Virtqueue& ring) {
  std::optional<socpuppet::Virtqueue::Chain> chain = ring.Next();
  if (!chain.has_value()) {
    ADD_FAILURE() << "The driver had made no chain available.";
    return {};
  }
  return *std::move(chain);
}

#endif  // TESTS_CPP_SUPPORT_VIRTQUEUE_DRIVER_H_
