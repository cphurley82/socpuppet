#include "socpuppet/core/virtqueue.h"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/memory_store.h"

namespace socpuppet {

namespace {

// Where the driver's memory is in these tests, 64 KiB of it, above 4 GiB so
// that an address in it needs all of its 64 bits.
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

// Descriptor flags, virtio 1.2 section 2.7.5: a descriptor with neither is
// one the device reads.
constexpr std::uint16_t kReadable = 0;
constexpr std::uint16_t kNext = 1;
constexpr std::uint16_t kWrite = 2;

// `length` bytes in which no two neighbours are the same, and which do not
// repeat every 256 bytes, so that bytes read from the wrong buffer (they
// are 0x100 apart) are not taken for the right ones.
std::vector<std::uint8_t> SomeBytes(std::size_t length) {
  std::vector<std::uint8_t> data(length);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(1 + index + (index / 251));
  }
  return data;
}

// The driver's side of a split virtqueue of `kSize` entries, laid out in
// the memory as the specification lays it out (virtio 1.2, section 2.7):
// the descriptor table, then the available ring, then the used ring.
struct Driver {
  static constexpr std::uint16_t kSize = 8;
  static constexpr std::uint64_t kDesc = kMemory + 0x1000;
  static constexpr std::uint64_t kAvail = kMemory + 0x2000;
  static constexpr std::uint64_t kUsed = kMemory + 0x3000;
  // Where a buffer the driver hands over begins; each is 0x100 apart.
  static constexpr std::uint64_t kBuffers = kMemory + 0x4000;

  MemoryAt memory{kMemory};
  Virtqueue queue{
      memory, {.desc = kDesc, .avail = kAvail, .used = kUsed, .size = kSize}};
  std::uint16_t available = 0;

  // Describes buffer `index`: `length` bytes at its address, with `flags`,
  // chained to descriptor `next` if the flags say so.
  std::uint64_t Describe(std::uint16_t index, std::uint32_t length,
                         std::uint16_t flags, std::uint16_t next = 0) {
    const std::uint64_t address = kBuffers + 0x100 * index;
    std::vector<std::uint8_t> descriptor(16);
    std::span<std::uint8_t> bytes = descriptor;
    StoreLittleEndian(address, bytes.subspan(0, 8));
    StoreLittleEndian(length, bytes.subspan(8, 4));
    StoreLittleEndian(flags, bytes.subspan(12, 2));
    StoreLittleEndian(next, bytes.subspan(14, 2));
    EXPECT_TRUE(memory.Write(kDesc + 16 * index, descriptor));
    return address;
  }
  // Fills the buffer of descriptor `index` with `bytes`.
  void Fill(std::uint16_t index, std::span<const std::uint8_t> bytes) {
    EXPECT_TRUE(memory.Write(kBuffers + 0x100 * index, bytes));
  }
  // Puts the chain that starts at descriptor `head` in the available ring
  // and moves the ring's index on.
  void MakeAvailable(std::uint16_t head) {
    EXPECT_TRUE(memory.Write(kAvail + 4 + 2 * (available % kSize),
                             LittleEndianBytes(head)));
    ++available;
    EXPECT_TRUE(memory.Write(kAvail + 2, LittleEndianBytes(available)));
  }
};

TEST(WhenTheDriverMakesAChainOfOneReadableDescriptorAvailable,
     TheDeviceGetsTheChainWithItsBytes) {
  Driver driver;
  const std::vector<std::uint8_t> bytes = SomeBytes(48);
  driver.Describe(0, static_cast<std::uint32_t>(bytes.size()), kReadable);
  driver.Fill(0, bytes);
  driver.MakeAvailable(0);

  const std::optional<Virtqueue::Chain> chain = driver.queue.Next();

  ASSERT_TRUE(chain.has_value());
  EXPECT_EQ(driver.queue.Read(*chain), bytes);
}

TEST(WhenTheDriverMakesAChainOfThreeDescriptorsAvailable,
     TheDeviceFollowsNextAndSplitsWhatItReadsFromWhatItWrites) {
  Driver driver;
  const std::vector<std::uint8_t> first = SomeBytes(16);
  const std::vector<std::uint8_t> second = SomeBytes(300);
  driver.Describe(0, static_cast<std::uint32_t>(first.size()),
                  kReadable | kNext, 1);
  driver.Describe(1, static_cast<std::uint32_t>(second.size()),
                  kReadable | kNext, 2);
  const std::uint64_t answer = driver.Describe(2, 64, kWrite);
  driver.Fill(0, first);
  driver.Fill(1, second);
  driver.MakeAvailable(0);

  const std::optional<Virtqueue::Chain> chain = driver.queue.Next();

  ASSERT_TRUE(chain.has_value());
  std::vector<std::uint8_t> both = first;
  both.insert(both.end(), second.begin(), second.end());
  EXPECT_EQ(driver.queue.Read(*chain), both);
  ASSERT_EQ(chain->writable.size(), 1U);
  EXPECT_EQ(chain->writable.front().address, answer);
  EXPECT_EQ(chain->writable.front().length, 64U);
}

TEST(WhenTheDriverHasMadeNothingMoreAvailable, TheDeviceGetsNoChain) {
  Driver driver;
  driver.Describe(0, 8, kReadable);
  driver.MakeAvailable(0);
  driver.queue.Next();

  EXPECT_FALSE(driver.queue.Next().has_value());
}

}  // namespace

}  // namespace socpuppet
