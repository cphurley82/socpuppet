#ifndef SOCPUPPET_CORE_VIRTQUEUE_H_
#define SOCPUPPET_CORE_VIRTQUEUE_H_

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"

namespace socpuppet {

// The device's side of a split virtqueue (virtio 1.2, section 2.7): the
// descriptor table, the available ring the driver fills and the used ring
// the device fills, all in the driver's memory.
//
// A request goes round like this: the driver chains descriptors and puts
// the head in the available ring; the device takes the chain (`Next`),
// reads what the driver gave it (`Read`), writes its answer (`Write`) and
// gives the chain back on the used ring (`Used`). The driver then takes an
// interrupt, which is the transport's business, not this class's.
class Virtqueue {
 public:
  // Where the queue's three parts are in the driver's memory, and how many
  // entries it has. The driver tells the transport, and the transport makes
  // a queue from it; to set a queue up again is to make a new one.
  struct Layout {
    std::uint64_t desc;
    std::uint64_t avail;
    std::uint64_t used;
    std::uint16_t size;
  };

  // A run of bytes in the driver's memory that one descriptor describes.
  struct Buffer {
    std::uint64_t address;
    std::uint32_t length;
  };

  // One request from the driver: the chain of descriptors that starts at
  // `head`, split into the buffers the device reads and the ones it writes.
  struct Chain {
    std::uint16_t head;
    std::vector<Buffer> readable;
    std::vector<Buffer> writable;
  };

  Virtqueue(MemoryPort& memory, Layout layout)
      : memory_(memory), layout_(layout) {}

  // The next chain the driver has made available, if any.
  std::optional<Chain> Next() {
    if (broken_ || Load16(layout_.avail + kRingIndex) == seen_) {
      return std::nullopt;
    }
    const std::uint16_t head =
        Load16(layout_.avail + kRingEntries + 2 * (seen_ % layout_.size));
    ++seen_;
    Chain chain{.head = head, .readable = {}, .writable = {}};
    std::uint16_t index = head;
    // A chain cannot be longer than the table it is in, so one that is has
    // gone round in a circle.
    for (std::uint16_t followed = 0; followed < layout_.size; ++followed) {
      const Descriptor descriptor = LoadDescriptor(index);
      (descriptor.flags & kWrite ? chain.writable : chain.readable)
          .push_back(
              {.address = descriptor.address, .length = descriptor.length});
      if (!(descriptor.flags & kNext)) {
        return chain;
      }
      index = descriptor.next;
    }
    broken_ = true;
    return std::nullopt;
  }

  // The bytes of a chain's readable buffers, in order.
  std::vector<std::uint8_t> Read(const Chain& chain) {
    std::vector<std::uint8_t> bytes;
    for (const Buffer& buffer : chain.readable) {
      const std::size_t start = bytes.size();
      bytes.resize(start + buffer.length);
      memory_.Read(buffer.address, std::span(bytes).subspan(start));
    }
    return bytes;
  }

  // Fills a chain's writable buffers with `bytes`, in order, as far as they
  // go, and says how many bytes went: what `Used` is then told.
  std::uint32_t Write(const Chain& chain, std::span<const std::uint8_t> bytes) {
    std::uint32_t went = 0;
    for (const Buffer& buffer : chain.writable) {
      if (went == bytes.size()) {
        break;
      }
      const std::uint32_t part = std::min<std::uint32_t>(
          buffer.length, static_cast<std::uint32_t>(bytes.size() - went));
      memory_.Write(buffer.address, bytes.subspan(went, part));
      went += part;
    }
    return went;
  }

  // Gives a chain back to the driver, saying how many bytes of its writable
  // buffers the device wrote: the element first, then the index, so that a
  // driver reading the index never sees an element that is not there yet.
  void Used(const Chain& chain, std::uint32_t written) {
    std::array<std::uint8_t, kUsedElementBytes> element{};
    const std::span<std::uint8_t> fields = element;
    StoreLittleEndian(std::uint32_t{chain.head}, fields.subspan(0, 4));
    StoreLittleEndian(written, fields.subspan(4, 4));
    memory_.Write(layout_.used + kRingEntries +
                      kUsedElementBytes * (used_ % layout_.size),
                  element);
    ++used_;
    memory_.Write(layout_.used + kRingIndex, LittleEndianBytes(used_));
  }

  // Whether the driver has handed over a chain the device could not take,
  // after which the queue gives nothing more until a new one is made.
  bool Broken() const { return broken_; }

 private:
  // One entry of the descriptor table, section 2.7.5.
  struct Descriptor {
    std::uint64_t address;
    std::uint32_t length;
    std::uint16_t flags;
    std::uint16_t next;
  };
  static constexpr std::uint64_t kDescriptorBytes = 16;
  // Its flags: the chain goes on at `next`; the device writes this buffer.
  static constexpr std::uint16_t kNext = 1;
  static constexpr std::uint16_t kWrite = 2;
  // Both rings begin with 16-bit flags, then the 16-bit index, then the
  // entries (sections 2.7.6 and 2.7.8).
  static constexpr std::uint64_t kRingIndex = 2;
  static constexpr std::uint64_t kRingEntries = 4;
  // One element of the used ring: the chain's head and how many bytes were
  // written to it.
  static constexpr std::uint64_t kUsedElementBytes = 8;

  Descriptor LoadDescriptor(std::uint16_t index) {
    std::array<std::uint8_t, kDescriptorBytes> bytes{};
    memory_.Read(layout_.desc + kDescriptorBytes * index, bytes);
    const std::span<const std::uint8_t> fields = bytes;
    return {.address = LoadLittleEndian<std::uint64_t>(fields.subspan(0, 8)),
            .length = LoadLittleEndian<std::uint32_t>(fields.subspan(8, 4)),
            .flags = LoadLittleEndian<std::uint16_t>(fields.subspan(12, 2)),
            .next = LoadLittleEndian<std::uint16_t>(fields.subspan(14, 2))};
  }

  std::uint16_t Load16(std::uint64_t address) {
    std::array<std::uint8_t, 2> bytes{};
    memory_.Read(address, bytes);
    return LoadLittleEndian<std::uint16_t>(bytes);
  }

  MemoryPort& memory_;
  Layout layout_;
  // How far along the available ring the device has looked, and how many
  // chains it has given back on the used ring.
  std::uint16_t seen_ = 0;
  std::uint16_t used_ = 0;
  bool broken_ = false;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTQUEUE_H_
