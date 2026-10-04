#include "socpuppet/core/script.h"

#include <cstdint>
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

}  // namespace

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

  script.GiveBack(0xC0FFEE);
  const Op* write = script.Next();

  ASSERT_NE(write, nullptr);
  EXPECT_EQ(std::get<Write32>(*write).value, 0xC0FFEEU);
}

}  // namespace socpuppet
