#include "socpuppet/core/system_controller_logic.h"

#include <array>
#include <cstdint>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/regs/system_controller.h"

namespace socpuppet {

namespace {

constexpr std::uint32_t kDie = 3;
constexpr std::uint32_t kBootAddress = 0x1020'0000;

// A system controller as its CPU sees it.
struct Rig {
  SystemControllerLogic controller{kDie, kBootAddress};

  // The bytes do not start out as zeros, so that a register the
  // controller leaves untouched is not taken for one that reads as zero.
  std::uint32_t Read32(std::uint64_t offset) const {
    std::array<std::uint8_t, 4> bytes{0xAA, 0xAA, 0xAA, 0xAA};
    EXPECT_TRUE(controller.ReadRegister(offset, bytes));
    return LoadLittleEndian<std::uint32_t>(bytes);
  }
  bool Write32(std::uint64_t offset, std::uint32_t value) {
    return controller.WriteRegister(offset, LittleEndianBytes(value));
  }
};

}  // namespace

TEST(WhenThePowerHasJustComeOn, TheResetCauseReadsPowerOn) {
  const Rig rig;

  EXPECT_EQ(rig.Read32(SYSTEM_CONTROLLER_RESET_CAUSE),
            SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON);
}

TEST(WhenThePowerHasJustComeOn, TheCpuIsNotHeldInReset) {
  const Rig rig;

  EXPECT_FALSE(rig.controller.Reset());
}

TEST(ASystemController, SaysWhichDieItWasBuiltFor) {
  const Rig rig;

  EXPECT_EQ(rig.Read32(SYSTEM_CONTROLLER_DIE), kDie);
}

TEST(ASystemController, SaysWhereItWasBuiltToBootFrom) {
  const Rig rig;

  EXPECT_EQ(rig.Read32(SYSTEM_CONTROLLER_BOOT_ADDRESS), kBootAddress);
}

TEST(WhenFirmwareReadsTheResetRequestItHasWritten, ItReadsAsZero) {
  Rig rig;
  rig.Write32(SYSTEM_CONTROLLER_RESET_REQUEST,
              SYSTEM_CONTROLLER_RESET_REQUEST_RESET);

  EXPECT_EQ(rig.Read32(SYSTEM_CONTROLLER_RESET_REQUEST), 0U);
}

TEST(WhileTheHoldLineIsHigh, TheCpuIsHeldInReset) {
  Rig rig;

  rig.controller.Hold(true);

  EXPECT_TRUE(rig.controller.Reset());
}

TEST(WhenTheHoldLineFalls, TheCpuIsLetGoAndTheCauseIsStillPowerOn) {
  Rig rig;
  rig.controller.Hold(true);

  rig.controller.Hold(false);

  EXPECT_FALSE(rig.controller.Reset());
  EXPECT_EQ(rig.Read32(SYSTEM_CONTROLLER_RESET_CAUSE),
            SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON);
}

TEST(WhenFirmwareWritesAOneToTheResetRequest, TheCpuIsResetUntilThePulseEnds) {
  Rig rig;

  EXPECT_TRUE(rig.Write32(SYSTEM_CONTROLLER_RESET_REQUEST,
                          SYSTEM_CONTROLLER_RESET_REQUEST_RESET));

  EXPECT_TRUE(rig.controller.Reset());
  rig.controller.EndPulse();
  EXPECT_FALSE(rig.controller.Reset());
}

TEST(WhenFirmwareWritesAOneToTheResetRequest, TheCauseReadsSoftware) {
  Rig rig;

  rig.Write32(SYSTEM_CONTROLLER_RESET_REQUEST,
              SYSTEM_CONTROLLER_RESET_REQUEST_RESET);

  EXPECT_EQ(rig.Read32(SYSTEM_CONTROLLER_RESET_CAUSE),
            SYSTEM_CONTROLLER_RESET_CAUSE_SOFTWARE);
}

TEST(WhenFirmwareWritesAZeroToTheResetRequest, NothingIsReset) {
  Rig rig;

  EXPECT_TRUE(rig.Write32(SYSTEM_CONTROLLER_RESET_REQUEST, 0));

  EXPECT_FALSE(rig.controller.Reset());
  EXPECT_EQ(rig.Read32(SYSTEM_CONTROLLER_RESET_CAUSE),
            SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON);
}

TEST(WhenTheWatchdogBites, TheCpuIsResetUntilThePulseEnds) {
  Rig rig;

  rig.controller.Bite();

  EXPECT_TRUE(rig.controller.Reset());
  rig.controller.EndPulse();
  EXPECT_FALSE(rig.controller.Reset());
}

TEST(WhenTheWatchdogBites, TheCauseReadsWatchdog) {
  Rig rig;

  rig.controller.Bite();

  EXPECT_EQ(rig.Read32(SYSTEM_CONTROLLER_RESET_CAUSE),
            SYSTEM_CONTROLLER_RESET_CAUSE_WATCHDOG);
}

TEST(WhenTheWatchdogBitesAfterFirmwareAskedForAReset,
     TheCauseIsTheLaterOfTheTwo) {
  Rig rig;
  rig.Write32(SYSTEM_CONTROLLER_RESET_REQUEST,
              SYSTEM_CONTROLLER_RESET_REQUEST_RESET);
  rig.controller.EndPulse();

  rig.controller.Bite();

  EXPECT_EQ(rig.Read32(SYSTEM_CONTROLLER_RESET_CAUSE),
            SYSTEM_CONTROLLER_RESET_CAUSE_WATCHDOG);
}

TEST(WhenAPulseEndsWhileTheHoldLineIsHigh, TheCpuIsStillHeld) {
  Rig rig;
  rig.controller.Hold(true);
  rig.controller.Bite();

  rig.controller.EndPulse();

  EXPECT_TRUE(rig.controller.Reset());
}

// A register of the controller's, by its offset and by its name.
struct Register {
  std::uint64_t offset;
  const char* name;
};

class ARegisterThatIsNotFirmwaresToWrite
    : public ::testing::TestWithParam<Register> {};

TEST_P(ARegisterThatIsNotFirmwaresToWrite, RefusesAWriteAndKeepsWhatItHad) {
  Rig rig;
  const std::uint32_t before = rig.Read32(GetParam().offset);

  EXPECT_FALSE(rig.Write32(GetParam().offset, 0xFFFF'FFFF));

  EXPECT_EQ(rig.Read32(GetParam().offset), before);
}

INSTANTIATE_TEST_SUITE_P(
    OfASystemController, ARegisterThatIsNotFirmwaresToWrite,
    ::testing::Values(Register{SYSTEM_CONTROLLER_DIE, "Die"},
                      Register{SYSTEM_CONTROLLER_BOOT_ADDRESS, "BootAddress"},
                      Register{SYSTEM_CONTROLLER_RESET_CAUSE, "ResetCause"}),
    [](const auto& the_register) { return the_register.param.name; });

// Half a register that would, whole, ask for a reset.
constexpr std::array<std::uint8_t, 2> kHalfARequest{
    SYSTEM_CONTROLLER_RESET_REQUEST_RESET, 0};

TEST(WhenAnAccessToASystemControllerIsNot32BitsWide, ItIsRefused) {
  Rig rig;
  std::array<std::uint8_t, 2> half{};

  EXPECT_FALSE(rig.controller.ReadRegister(SYSTEM_CONTROLLER_DIE, half));
  EXPECT_FALSE(rig.controller.WriteRegister(SYSTEM_CONTROLLER_RESET_REQUEST,
                                            kHalfARequest));

  EXPECT_FALSE(rig.controller.Reset());
}

TEST(WhenAnAccessToASystemControllerStartsPartWayIntoARegister, ItIsRefused) {
  Rig rig;
  std::array<std::uint8_t, 4> word{};

  EXPECT_FALSE(rig.controller.ReadRegister(SYSTEM_CONTROLLER_DIE + 2, word));
}

// The block has room for more registers than it has.
TEST(WhenAnAccessToASystemControllerIsBesideItsRegisters, ItIsRefused) {
  Rig rig;
  std::array<std::uint8_t, 4> word{};
  const std::uint64_t beside = SYSTEM_CONTROLLER_RESET_REQUEST + 4;

  EXPECT_FALSE(rig.controller.ReadRegister(beside, word));
  EXPECT_FALSE(rig.Write32(beside, SYSTEM_CONTROLLER_RESET_REQUEST_RESET));

  EXPECT_FALSE(rig.controller.Reset());
}

}  // namespace socpuppet
