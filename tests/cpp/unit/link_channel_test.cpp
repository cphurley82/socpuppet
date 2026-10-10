#include "socpuppet/core/link_channel.h"

#include <chrono>

#include <gtest/gtest.h>

#include "socpuppet/core/time.h"

namespace socpuppet {

using std::chrono_literals::operator""ns;

// A link that takes 20 ns to carry anything across and carries 16 bytes of
// it in a nanosecond.
LinkChannel AChannel() { return LinkChannel{20ns, 16}; }

TEST(WhenATransactionCrossesAnIdleLink, ItArrivesALatencyAndItsBytesLater) {
  LinkChannel channel = AChannel();

  // 64 bytes at 16 a nanosecond take 4 ns to go, and the crossing is 20.
  EXPECT_EQ(channel.Cross(64, 0ns), 24ns);
}

TEST(WhenTwoTransactionsLeaveAtOnce, TheSecondWaitsForTheFirstsBytes) {
  LinkChannel channel = AChannel();
  channel.Cross(64, 0ns);

  // The first transaction's bytes occupy the link until 4 ns, so this one
  // starts going there and arrives a latency after that.
  EXPECT_EQ(channel.Cross(64, 0ns), 28ns);
}

TEST(WhenATransactionLeavesAfterTheLinkIsFreeAgain, ItWaitsForNothing) {
  LinkChannel channel = AChannel();
  channel.Cross(64, 0ns);  // the link carries its bytes until 4 ns

  EXPECT_EQ(channel.Cross(64, 10ns), 34ns);
}

TEST(WhenATransactionsBytesDoNotFillWholePicoseconds, TheLastOneCountsWhole) {
  LinkChannel channel = AChannel();

  // 3 bytes at 16 a nanosecond take 187.5 ps, and no byte has crossed
  // before its time is up.
  EXPECT_EQ(channel.Cross(3, 0ns), 20ns + Picoseconds{188});
}

TEST(WhenATransactionCarriesNoBytes, ItStillTakesTheLinksLatency) {
  LinkChannel channel = AChannel();

  EXPECT_EQ(channel.Cross(0, 0ns), 20ns);
}

}  // namespace socpuppet
