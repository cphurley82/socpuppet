#include "tests/cpp/support/qbox_fates.h"

#include <string>

#include <gtest/gtest.h>

namespace {

TEST(WhenAFatesPatternHasNoStar, ItMatchesThatNameAndNoOther) {
  EXPECT_TRUE(MatchesFate("Spam.Eggs", "Spam.Eggs"));
  EXPECT_FALSE(MatchesFate("Spam.EggsAndSpam", "Spam.Eggs"));
  EXPECT_FALSE(MatchesFate("Spam.Egg", "Spam.Eggs"));
}

TEST(WhenAFatesPatternHasAStar, ItStandsForAnyRunOfCharactersOrNone) {
  EXPECT_TRUE(MatchesFate("Spam.Eggs", "Spam.*"));
  EXPECT_TRUE(MatchesFate("Spam.", "Spam.*"));
  EXPECT_TRUE(MatchesFate("All/Spam.Eggs/ASwapOverTheBus", "All/*OverTheBus"));
  EXPECT_FALSE(
      MatchesFate("All/Spam.Eggs/ASwapByDirectAccess", "All/*OverTheBus"));
}

TEST(WhenATestIsAQboxFate, ItsReasonIsGiven) {
  EXPECT_EQ(WhyQboxFails("WhenXlenIs32.TheCpusRegistersAre32BitsWide"),
            k64BitOnly);
}

TEST(WhenATestIsNoQboxFate, NoReasonIsGiven) {
  EXPECT_TRUE(
      WhyQboxFails("WhenXlenIs64.TheCpusRegistersAre64BitsWide").empty());
}

TEST(WhenEveryFateIsLeftOutOfARun, TheFilterNamesEachAfterTheMinus) {
  const std::string filter = AllQboxFates();

  EXPECT_TRUE(filter.starts_with("-WhenXlenIs32.*:"));
  EXPECT_NE(filter.find(":WhenA64BitAndA32BitCpuShareASimulation.*:"),
            std::string::npos);
}

}  // namespace
