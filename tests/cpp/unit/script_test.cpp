#include "socpuppet/core/script.h"

#include <cstdint>
#include <utility>
#include <variant>
#include <vector>

#include <gtest/gtest.h>

namespace socpuppet {

namespace {

Script TwoWritesThenAWait() {
  co_await Write32(0x10, 0xAAAA);
  co_await Write32(0x14, 0xBBBB);
  co_await Wait(Picoseconds{500});
}

Script ReadThenWriteBack(std::uint64_t from, std::uint64_t to) {
  const std::uint32_t value = co_await Read32(from);
  co_await Write32(to, value);
}

Script WriteBytes(std::vector<std::uint8_t> bytes) {
  co_await Write(0x10, std::move(bytes));
}

Script ReadThreeBytesThenWriteThemBack() {
  std::vector<std::uint8_t> bytes = co_await Read(0x10, 3);
  co_await Write(0x20, std::move(bytes));
}

}  // namespace

TEST(WhenAScriptAwaitsAWriteOfBytes, TheOpCarriesTheBytes) {
  Script script = WriteBytes({0x11, 0x22, 0x33});

  const Op* write = script.Next();

  ASSERT_NE(write, nullptr);
  EXPECT_EQ(std::get<Write>(*write).data,
            (std::vector<std::uint8_t>{0x11, 0x22, 0x33}));
}

TEST(WhenAScriptAwaitsAReadOfBytes, ItGetsTheBytesTheBusGaveBack) {
  Script script = ReadThreeBytesThenWriteThemBack();
  script.Next();  // the read

  script.GiveBack(std::vector<std::uint8_t>{0xAA, 0xBB, 0xCC});
  const Op* write = script.Next();

  ASSERT_NE(write, nullptr);
  EXPECT_EQ(std::get<Write>(*write).data,
            (std::vector<std::uint8_t>{0xAA, 0xBB, 0xCC}));
}

TEST(WhenAScriptAwaitsSeveralOps, TheyComeOutInTheOrderItAwaitedThem) {
  Script script = TwoWritesThenAWait();
  std::vector<Op> ops;

  while (const Op* op = script.Next()) ops.push_back(*op);

  ASSERT_EQ(ops.size(), 3U);
  EXPECT_EQ(std::get<Write32>(ops[0]).address, 0x10U);
  EXPECT_EQ(std::get<Write32>(ops[1]).address, 0x14U);
  EXPECT_EQ(std::get<Wait>(ops[2]).duration, Picoseconds{500});
}

TEST(WhenAScriptAwaitsARead, ItGetsTheValueTheBusGaveBack) {
  Script script = ReadThenWriteBack(0x10, 0x20);
  script.Next();  // the read

  script.GiveBack(std::uint32_t{0xC0FFEE});
  const Op* write = script.Next();

  ASSERT_NE(write, nullptr);
  EXPECT_EQ(std::get<Write32>(*write).value, 0xC0FFEEU);
}

}  // namespace socpuppet
