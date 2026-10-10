#include "socpuppet/core/command_status.h"

#include <cstdint>

#include <gtest/gtest.h>

#include "socpuppet/regs/command_device.h"

namespace socpuppet {

namespace {

// A status after a command that was carried out, or one that could not be.
CommandStatus AfterACommand(bool carried_out) {
  CommandStatus status;
  status.Start();
  status.Finish(carried_out);
  return status;
}

}  // namespace

TEST(WhenADeviceHasBeenGivenNoCommandYet, ItsStatusSaysNothing) {
  const CommandStatus status;

  EXPECT_EQ(status.Status(), 0U);
}

TEST(WhenADeviceIsGivenACommand, ItsStatusSaysBusyAndNothingElse) {
  CommandStatus status;

  status.Start();

  EXPECT_EQ(status.Status(), COMMAND_DEVICE_STATUS_BUSY);
}

TEST(WhenADeviceHasCarriedItsCommandOut, ItsStatusSaysDoneAndNothingElse) {
  EXPECT_EQ(AfterACommand(true).Status(), COMMAND_DEVICE_STATUS_DONE);
}

TEST(WhenADeviceCouldNotCarryItsCommandOut, ItsStatusSaysErrorAndNothingElse) {
  EXPECT_EQ(AfterACommand(false).Status(), COMMAND_DEVICE_STATUS_ERROR);
}

// So that the status is always about the last command.
TEST(WhenADeviceIsGivenItsNextCommand, HowTheLastOneWentIsForgotten) {
  CommandStatus status = AfterACommand(false);

  status.Start();

  EXPECT_EQ(status.Status(), COMMAND_DEVICE_STATUS_BUSY);
}

TEST(WhenTheCpuWritesAOneToDoneOrError, TheBitIsCleared) {
  CommandStatus done = AfterACommand(true);
  CommandStatus error = AfterACommand(false);

  done.WriteStatus(COMMAND_DEVICE_STATUS_DONE);
  error.WriteStatus(COMMAND_DEVICE_STATUS_ERROR);

  EXPECT_EQ(done.Status(), 0U);
  EXPECT_EQ(error.Status(), 0U);
}

TEST(WhenTheCpuWritesAZeroToDone, DoneStaysSet) {
  CommandStatus status = AfterACommand(true);

  status.WriteStatus(COMMAND_DEVICE_STATUS_ERROR);

  EXPECT_EQ(status.Status(), COMMAND_DEVICE_STATUS_DONE);
}

// Busy is the device's to say, and not the CPU's to take back.
TEST(WhenTheCpuWritesAOneToBusy, TheDeviceStaysBusy) {
  CommandStatus status;
  status.Start();

  status.WriteStatus(COMMAND_DEVICE_STATUS_BUSY);

  EXPECT_EQ(status.Status(), COMMAND_DEVICE_STATUS_BUSY);
}

TEST(WhenTheCpuEnablesEveryInterruptThereCouldBe, OnlyDoneAndErrorAreEnabled) {
  CommandStatus status;

  status.WriteInterruptEnable(0xFFFF'FFFF);

  EXPECT_EQ(status.InterruptEnable(),
            COMMAND_DEVICE_STATUS_DONE | COMMAND_DEVICE_STATUS_ERROR);
}

TEST(WhenAnEnabledStatusBitIsSet, TheDeviceInterrupts) {
  CommandStatus status;
  status.WriteInterruptEnable(COMMAND_DEVICE_STATUS_DONE);
  status.Start();
  const bool while_busy = status.Interrupting();

  status.Finish(true);

  EXPECT_FALSE(while_busy);
  EXPECT_TRUE(status.Interrupting());
}

TEST(WhenTheStatusBitThatIsSetIsNotEnabled, TheDeviceDoesNotInterrupt) {
  CommandStatus status;
  status.WriteInterruptEnable(COMMAND_DEVICE_STATUS_DONE);
  status.Start();

  status.Finish(false);

  EXPECT_FALSE(status.Interrupting());
}

TEST(WhenTheCpuClearsTheBitThatInterruptedIt, TheDeviceStopsInterrupting) {
  CommandStatus status;
  status.WriteInterruptEnable(COMMAND_DEVICE_STATUS_DONE);
  status.Start();
  status.Finish(true);

  status.WriteStatus(COMMAND_DEVICE_STATUS_DONE);

  EXPECT_FALSE(status.Interrupting());
}

}  // namespace socpuppet
