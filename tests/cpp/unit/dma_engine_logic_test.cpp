#include "socpuppet/core/dma_engine_logic.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/memory_store.h"

namespace socpuppet {

namespace {

// The engine's registers, each 32 bits wide, as docs/models/dma-engine.md
// gives them.
constexpr std::uint64_t kCommand = 0x00;
constexpr std::uint64_t kStatus = 0x04;
constexpr std::uint64_t kHostAddressLow = 0x0C;
constexpr std::uint64_t kHostAddressHigh = 0x10;
constexpr std::uint64_t kLocalAddress = 0x14;
constexpr std::uint64_t kLength = 0x18;

// What can be written to the command register.
constexpr std::uint32_t kFromHost = 1;

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;

// Where the two memories are in these tests, 64 KiB of each. The host's is
// above 4 GiB, so that an address of it needs both halves.
constexpr std::uint64_t kHost = 0x1'0000'0000;
constexpr std::uint64_t kLocal = 0x4000'0000;
constexpr std::size_t kMemorySize = 0x1'0000;

// A memory at some address, on one of the engine's two ports.
class MemoryAt : public MemoryPort {
 public:
  explicit MemoryAt(std::uint64_t base) : base_(base) {}

  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return address >= base_ && store_.Read(address - base_, out);
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return address >= base_ && store_.Write(address - base_, in);
  }

  // What the memory holds at `address`, `length` bytes of it.
  std::vector<std::uint8_t> At(std::uint64_t address, std::size_t length) {
    std::vector<std::uint8_t> data(length);
    EXPECT_TRUE(Read(address, data));
    return data;
  }

 private:
  std::uint64_t base_;
  MemoryStore store_{kMemorySize};
};

// `length` bytes in which no two neighbours are the same, and which do not
// repeat for a long way.
std::vector<std::uint8_t> SomeBytes(std::size_t length) {
  std::vector<std::uint8_t> data(length);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(1 + index + (index / 251));
  }
  return data;
}

// An engine between a host's memory and the SSD's own, as its CPU sees it.
struct Rig {
  MemoryAt host{kHost};
  MemoryAt local{kLocal};
  DmaEngineLogic engine{host, local};

  bool Write32(std::uint64_t offset, std::uint32_t value) {
    return engine.WriteRegister(offset, LittleEndianBytes(value));
  }
  // The bytes do not start out as zeros, so that a register the engine
  // leaves untouched is not taken for one that reads as zero.
  std::uint32_t Read32(std::uint64_t offset) {
    std::array<std::uint8_t, 4> bytes{0xA5, 0xA5, 0xA5, 0xA5};
    EXPECT_TRUE(engine.ReadRegister(offset, bytes));
    return LoadLittleEndian<std::uint32_t>(bytes);
  }
  // Says what to move: `length` bytes, between `host_address` and
  // `local_address`.
  void Describe(std::uint64_t host_address, std::uint64_t local_address,
                std::uint32_t length) {
    Write32(kHostAddressLow, static_cast<std::uint32_t>(host_address));
    Write32(kHostAddressHigh, static_cast<std::uint32_t>(host_address >> 32));
    Write32(kLocalAddress, static_cast<std::uint32_t>(local_address));
    Write32(kLength, length);
  }
  // Gives a command and lets the engine carry it out.
  void Do(std::uint32_t command) {
    Write32(kCommand, command);
    engine.CarryOut();
  }
};

}  // namespace

TEST(WhenADmaEngineIsToldToCopyFromTheHost, TheBytesArriveInTheSsdsMemory) {
  Rig rig;
  rig.host.Write(kHost + 0x100, SomeBytes(24));
  rig.Describe(kHost + 0x100, kLocal + 0x200, 24);

  rig.Do(kFromHost);

  EXPECT_EQ(rig.local.At(kLocal + 0x200, 24), SomeBytes(24));
  EXPECT_EQ(rig.Read32(kStatus), kDone);
}

}  // namespace socpuppet
