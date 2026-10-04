#include "socpuppet/core/script.h"

#include <cstdint>
#include <variant>
#include <vector>

#include <gtest/gtest.h>

namespace socpuppet {

namespace {

Script two_writes_then_a_wait() {
  co_await write32(0x10, 0xAAAA);
  co_await write32(0x14, 0xBBBB);
  co_await wait_for(Picoseconds{500});
}

Script read_then_write_back(std::uint64_t from, std::uint64_t to) {
  const std::uint32_t value = co_await read32(from);
  co_await write32(to, value);
}

}  // namespace

TEST(WhenAScriptAwaitsSeveralOps, TheyComeOutInTheOrderItAwaitedThem) {
  Script script = two_writes_then_a_wait();
  std::vector<Op> ops;

  while (const Op* op = script.next()) ops.push_back(*op);

  ASSERT_EQ(ops.size(), 3U);
  EXPECT_EQ(std::get<Write32>(ops[0]).address, 0x10U);
  EXPECT_EQ(std::get<Write32>(ops[1]).address, 0x14U);
  EXPECT_EQ(std::get<Wait>(ops[2]).duration, Picoseconds{500});
}

TEST(WhenAScriptAwaitsARead, ItGetsTheValueTheBusGaveBack) {
  Script script = read_then_write_back(0x10, 0x20);
  script.next();  // the read

  script.give_back(0xC0FFEE);
  const Op* write = script.next();

  ASSERT_NE(write, nullptr);
  EXPECT_EQ(std::get<Write32>(*write).value, 0xC0FFEEU);
}

}  // namespace socpuppet
