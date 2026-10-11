#ifndef TESTS_CPP_CONTRACTS_UART_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_UART_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"

// What every 16550-style UART must do, whatever is behind it. This is the
// part of the 16550 that a driver's console relies on, polled or driven by
// the interrupt.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, UartContract,
//                                  ::testing::Types<MyUart>);
// MyUart must fit the UART slot (see socpuppet/platform/slots.h).
template <socpuppet::UartSlot UartType>
class UartContract : public ::testing::Test {
 protected:
  // The 16550's registers, one byte each, by their offset. The first is
  // two: a write is a byte to transmit, and a read is a byte received.
  static constexpr std::uint64_t kTransmitHolding = 0;
  static constexpr std::uint64_t kReceiveBuffer = 0;
  // With the divisor latch open, the first two registers are the divisor
  // that sets the baud rate, low byte first.
  static constexpr std::uint64_t kDivisorLow = 0;
  static constexpr std::uint64_t kDivisorHigh = 1;
  // Which interrupts are enabled, a bit each. With the divisor latch
  // closed, as it is unless a test opens it.
  static constexpr std::uint64_t kInterruptEnable = 1;
  // Which interrupt is pending, as a code: the one with the highest
  // priority, if more than one is.
  static constexpr std::uint64_t kInterruptIdentification = 2;
  static constexpr std::uint64_t kLineControl = 3;
  static constexpr std::uint64_t kModemControl = 4;
  static constexpr std::uint64_t kLineStatus = 5;
  static constexpr std::uint64_t kScratch = 7;

  // Line control: the bit that opens the divisor latch.
  static constexpr std::uint8_t kDivisorLatchOpen = 0x80;
  // Line status: the transmit register can take a byte, and the
  // transmitter has nothing left to send.
  static constexpr std::uint8_t kTransmitterReady = 0x60;
  // Line status: a received byte is waiting to be read.
  static constexpr std::uint8_t kDataReady = 0x01;

  // Interrupt enable: a received byte is waiting, and the transmit
  // register can take another byte.
  static constexpr std::uint8_t kReceivedDataAvailable = 0x01;
  static constexpr std::uint8_t kTransmitterEmpty = 0x02;
  // Interrupt identification, its low three bits: none is pending, the
  // transmit register is empty, and a received byte is waiting, which has
  // the higher priority of those two.
  static constexpr std::uint8_t kIdentificationBits = 0x07;
  static constexpr std::uint8_t kNonePending = 0x01;
  static constexpr std::uint8_t kTransmitterEmptyPending = 0x02;
  static constexpr std::uint8_t kReceivedDataPending = 0x04;

  // Not a value any test expects, so that a read the UART leaves unanswered
  // shows.
  static constexpr std::uint8_t kUnanswered = 0xA5;

  UartContract() { uart_.irq.bind(interrupt_); }

  // Runs `body` in a simulation thread wired to the UART, to completion.
  void OnTheBus(std::function<void(BusDriver&)> body) {
    BusDriver driver{"driver", std::move(body)};
    driver.socket.bind(uart_.socket);
    sc_core::sc_start();
  }

  // Which interrupt the UART says is pending.
  static std::uint8_t PendingInterrupt(BusDriver& bus) {
    return ReadRegister(bus, kInterruptIdentification) & kIdentificationBits;
  }

  // Whether the UART is interrupting, once what was just done has settled.
  bool Interrupting(BusDriver& bus) {
    Settle(bus);
    return interrupt_.read();
  }

  // Writes one byte to the register at `offset`.
  static void WriteRegister(BusDriver& bus, std::uint64_t offset,
                            std::uint8_t value) {
    bus.Write(offset, std::array<std::uint8_t, 1>{value});
  }

  // Reads the register at `offset`.
  static std::uint8_t ReadRegister(BusDriver& bus, std::uint64_t offset) {
    std::array<std::uint8_t, 1> value{kUnanswered};
    bus.Read(offset, value);
    return value[0];
  }

  // Lets a byte that was handed to the UART reach its registers, which it
  // does a delta cycle after it is handed over.
  static void Settle(BusDriver& bus) {
    bus.WaitFor(sc_core::sc_time{1, sc_core::SC_NS});
  }

  // The same, the way a debugger looks: in no simulated time.
  static std::uint8_t LookAtRegister(BusDriver& bus, std::uint64_t offset) {
    std::array<std::uint8_t, 1> value{kUnanswered};
    bus.DebugRead(offset, value);
    return value[0];
  }

  UartType uart_{"uart"};
  // A wire takes one driver, so a UART drives its line from one process
  // of its own, whether a byte came in or a register was written.
  sc_core::sc_signal<bool> interrupt_{"interrupt"};
};

TYPED_TEST_SUITE_P(UartContract);

TYPED_TEST_P(UartContract, BytesWrittenToTheTransmitRegisterBecomeTheOutput) {
  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kTransmitHolding, 'O');
    this->WriteRegister(bus, this->kTransmitHolding, 'K');
  });

  EXPECT_EQ(this->uart_.Output(), "OK");
}

TYPED_TEST_P(UartContract,
             AfterAByteIsWrittenTheLineStatusShowsTheTransmitterReady) {
  std::uint8_t status = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kTransmitHolding, 'O');
    status = this->ReadRegister(bus, this->kLineStatus);
  });

  EXPECT_EQ(status & this->kTransmitterReady, this->kTransmitterReady);
}

TYPED_TEST_P(UartContract,
             WithTheDivisorLatchOpenTheFirstTwoRegistersHoldTheDivisor) {
  std::uint8_t low = 0;
  std::uint8_t high = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kLineControl, this->kDivisorLatchOpen);
    this->WriteRegister(bus, this->kDivisorLow, 0x12);
    this->WriteRegister(bus, this->kDivisorHigh, 0x34);
    low = this->ReadRegister(bus, this->kDivisorLow);
    high = this->ReadRegister(bus, this->kDivisorHigh);
  });

  EXPECT_EQ(low, 0x12);
  EXPECT_EQ(high, 0x34);
}

TYPED_TEST_P(UartContract, WithTheDivisorLatchOpenNothingIsTransmitted) {
  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kLineControl, this->kDivisorLatchOpen);
    this->WriteRegister(bus, this->kDivisorLow, 'X');
  });

  EXPECT_EQ(this->uart_.Output(), "");
}

TYPED_TEST_P(UartContract,
             TheControlAndScratchRegistersReadBackWhatWasWritten) {
  std::uint8_t line_control = 0;
  std::uint8_t modem_control = 0;
  std::uint8_t scratch = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kLineControl, 0x03);
    this->WriteRegister(bus, this->kModemControl, 0x0B);
    this->WriteRegister(bus, this->kScratch, 0x5A);
    line_control = this->ReadRegister(bus, this->kLineControl);
    modem_control = this->ReadRegister(bus, this->kModemControl);
    scratch = this->ReadRegister(bus, this->kScratch);
  });

  EXPECT_EQ(line_control, 0x03);
  EXPECT_EQ(modem_control, 0x0B);
  EXPECT_EQ(scratch, 0x5A);
}

TYPED_TEST_P(UartContract, TheScratchRegisterIsSeenByADebugAccess) {
  std::uint8_t seen = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kScratch, 0x5A);
    seen = this->LookAtRegister(bus, this->kScratch);
  });

  EXPECT_EQ(seen, 0x5A);
}

TYPED_TEST_P(UartContract, WithNothingReceivedTheLineStatusShowsNoDataReady) {
  std::uint8_t status = this->kDataReady;

  this->OnTheBus([&](BusDriver& bus) {
    status = this->ReadRegister(bus, this->kLineStatus);
  });

  EXPECT_EQ(status & this->kDataReady, 0);
}

// What comes in on the serial line: whoever is at the other end has typed
// something. `Write` is the other end.
TYPED_TEST_P(UartContract,
             AByteThatComesInIsReadFromTheReceiveRegisterAndThenThereIsNone) {
  std::uint8_t status_before = 0;
  std::uint8_t byte = 0;
  std::uint8_t status_after = this->kDataReady;

  this->OnTheBus([&](BusDriver& bus) {
    this->uart_.Write("A");
    this->Settle(bus);
    status_before = this->ReadRegister(bus, this->kLineStatus);
    byte = this->ReadRegister(bus, this->kReceiveBuffer);
    status_after = this->ReadRegister(bus, this->kLineStatus);
  });

  EXPECT_EQ(status_before & this->kDataReady, this->kDataReady);
  EXPECT_EQ(byte, 'A');
  EXPECT_EQ(status_after & this->kDataReady, 0);
}

TYPED_TEST_P(
    UartContract,
    BytesThatComeInAreReadInTheOrderTheyCameWithDataReadyUntilTheLast) {
  std::uint8_t first = 0;
  std::uint8_t status_between = 0;
  std::uint8_t second = 0;
  std::uint8_t status_after = this->kDataReady;

  this->OnTheBus([&](BusDriver& bus) {
    this->uart_.Write("OK");
    this->Settle(bus);
    first = this->ReadRegister(bus, this->kReceiveBuffer);
    status_between = this->ReadRegister(bus, this->kLineStatus);
    second = this->ReadRegister(bus, this->kReceiveBuffer);
    status_after = this->ReadRegister(bus, this->kLineStatus);
  });

  EXPECT_EQ(first, 'O');
  EXPECT_EQ(status_between & this->kDataReady, this->kDataReady);
  EXPECT_EQ(second, 'K');
  EXPECT_EQ(status_after & this->kDataReady, 0);
}

TYPED_TEST_P(UartContract, BytesThatComeInWhileOthersWaitAreReadAfterThem) {
  std::uint8_t first = 0;
  std::uint8_t second = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->uart_.Write("O");
    this->uart_.Write("K");
    this->Settle(bus);
    first = this->ReadRegister(bus, this->kReceiveBuffer);
    second = this->ReadRegister(bus, this->kReceiveBuffer);
  });

  EXPECT_EQ(first, 'O');
  EXPECT_EQ(second, 'K');
}

// A driver enables an interrupt by reading the register, setting one bit
// and writing it back, so that it leaves the others as they were.
TYPED_TEST_P(UartContract, TheInterruptEnableRegisterReadsBackWhatWasWritten) {
  std::uint8_t enabled = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable,
                        this->kReceivedDataAvailable | this->kTransmitterEmpty);
    enabled = this->ReadRegister(bus, this->kInterruptEnable);
  });

  EXPECT_EQ(enabled, this->kReceivedDataAvailable | this->kTransmitterEmpty);
}

// Only reading the byte ends it. Asking which interrupt is pending does
// not, as it does for the transmitter's.
TYPED_TEST_P(
    UartContract,
    WithTheReceiveInterruptEnabledAByteThatComesInInterruptsUntilItIsRead) {
  bool before = true;
  std::uint8_t pending = 0;
  bool with_the_byte_waiting = false;
  bool once_read = true;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable,
                        this->kReceivedDataAvailable);
    before = this->Interrupting(bus);
    this->uart_.Write("A");
    this->Settle(bus);
    pending = this->PendingInterrupt(bus);
    with_the_byte_waiting = this->Interrupting(bus);
    this->ReadRegister(bus, this->kReceiveBuffer);
    once_read = this->Interrupting(bus);
  });

  EXPECT_FALSE(before);
  EXPECT_EQ(pending, this->kReceivedDataPending);
  EXPECT_TRUE(with_the_byte_waiting);
  EXPECT_FALSE(once_read);
}

// A driver enables its interrupts after whoever is at the other end may
// have started typing.
TYPED_TEST_P(UartContract,
             EnablingTheReceiveInterruptWithAByteAlreadyWaitingInterrupts) {
  bool interrupting = false;

  this->OnTheBus([&](BusDriver& bus) {
    this->uart_.Write("A");
    this->Settle(bus);
    this->WriteRegister(bus, this->kInterruptEnable,
                        this->kReceivedDataAvailable);
    interrupting = this->Interrupting(bus);
  });

  EXPECT_TRUE(interrupting);
}

TYPED_TEST_P(UartContract,
             WithTwoBytesWaitingReadingOneLeavesTheReceiveInterruptPending) {
  bool interrupting = false;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable,
                        this->kReceivedDataAvailable);
    this->uart_.Write("OK");
    this->Settle(bus);
    this->ReadRegister(bus, this->kReceiveBuffer);
    interrupting = this->Interrupting(bus);
  });

  EXPECT_TRUE(interrupting);
}

// A handler reads until there is nothing left, with nothing between the
// reads to let the UART catch up.
TYPED_TEST_P(UartContract,
             ReadingTwoBytesOneStraightAfterTheOtherEndsTheInterrupt) {
  bool interrupting = true;
  std::uint8_t pending = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable,
                        this->kReceivedDataAvailable);
    this->uart_.Write("OK");
    this->Settle(bus);
    this->ReadRegister(bus, this->kReceiveBuffer);
    this->ReadRegister(bus, this->kReceiveBuffer);
    interrupting = this->Interrupting(bus);
    pending = this->PendingInterrupt(bus);
  });

  EXPECT_FALSE(interrupting);
  EXPECT_EQ(pending, this->kNonePending);
}

// This is how a driver starts to transmit: it enables the interrupt and
// waits to be told there is room, which there is at once.
TYPED_TEST_P(UartContract,
             EnablingTheTransmitInterruptWhileNothingIsBeingSentInterrupts) {
  bool interrupting = false;
  std::uint8_t pending = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable, this->kTransmitterEmpty);
    interrupting = this->Interrupting(bus);
    pending = this->PendingInterrupt(bus);
  });

  EXPECT_TRUE(interrupting);
  EXPECT_EQ(pending, this->kTransmitterEmptyPending);
}

// On the chip, being told once is the whole of it: the interrupt is for
// the register becoming empty, and not for its being empty. It matters
// here for what the line then does: it falls, and can rise again.
TYPED_TEST_P(UartContract,
             ReadingWhichInterruptIsPendingEndsTheTransmitInterrupt) {
  bool before = false;
  std::uint8_t said = 0;
  bool after = true;
  std::uint8_t said_then = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable, this->kTransmitterEmpty);
    before = this->Interrupting(bus);
    said = this->PendingInterrupt(bus);
    after = this->Interrupting(bus);
    said_then = this->PendingInterrupt(bus);
  });

  EXPECT_TRUE(before);
  EXPECT_EQ(said, this->kTransmitterEmptyPending);
  EXPECT_FALSE(after);
  EXPECT_EQ(said_then, this->kNonePending);
}

// A driver enables the receive interrupt by writing the register back
// with one more bit set, and the transmit interrupt's bit may be among
// those it leaves as they were.
TYPED_TEST_P(UartContract,
             RewritingTheEnableRegisterDoesNotRaiseTheTransmitInterruptAgain) {
  bool interrupting = true;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable, this->kTransmitterEmpty);
    this->Settle(bus);
    this->PendingInterrupt(bus);
    this->WriteRegister(bus, this->kInterruptEnable,
                        this->kTransmitterEmpty | this->kReceivedDataAvailable);
    interrupting = this->Interrupting(bus);
  });

  EXPECT_FALSE(interrupting);
}

// A byte sent is gone at once here, so there is room again at once.
TYPED_TEST_P(UartContract,
             WithTheTransmitInterruptEnabledWritingAByteInterruptsAgain) {
  bool interrupting = false;
  std::uint8_t pending = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable, this->kTransmitterEmpty);
    this->Settle(bus);
    this->PendingInterrupt(bus);
    this->WriteRegister(bus, this->kTransmitHolding, 'O');
    interrupting = this->Interrupting(bus);
    pending = this->PendingInterrupt(bus);
  });

  EXPECT_TRUE(interrupting);
  EXPECT_EQ(pending, this->kTransmitterEmptyPending);
}

// A driver looks at one code and does one thing, so the UART says the one
// with the higher priority, and the other is still there afterwards.
TYPED_TEST_P(UartContract,
             WithBothPendingAReceivedByteIsSaidFirstAndTheTransmitterAfterIt) {
  std::uint8_t first = 0;
  std::uint8_t once_the_byte_is_read = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable,
                        this->kReceivedDataAvailable | this->kTransmitterEmpty);
    this->uart_.Write("A");
    this->Settle(bus);
    first = this->PendingInterrupt(bus);
    this->ReadRegister(bus, this->kReceiveBuffer);
    once_the_byte_is_read = this->PendingInterrupt(bus);
  });

  EXPECT_EQ(first, this->kReceivedDataPending);
  EXPECT_EQ(once_the_byte_is_read, this->kTransmitterEmptyPending);
}

// A driver with nothing more to send disables the interrupt.
TYPED_TEST_P(UartContract,
             DisablingTheTransmitInterruptWhileItIsPendingEndsIt) {
  bool before = false;
  bool after = true;

  this->OnTheBus([&](BusDriver& bus) {
    this->WriteRegister(bus, this->kInterruptEnable, this->kTransmitterEmpty);
    before = this->Interrupting(bus);
    this->WriteRegister(bus, this->kInterruptEnable, 0);
    after = this->Interrupting(bus);
  });

  EXPECT_TRUE(before);
  EXPECT_FALSE(after);
}

// A console that is polled enables nothing.
TYPED_TEST_P(UartContract, WithNoInterruptEnabledTheLineStaysLow) {
  bool interrupting = true;
  std::uint8_t pending = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->uart_.Write("A");
    this->WriteRegister(bus, this->kTransmitHolding, 'O');
    interrupting = this->Interrupting(bus);
    pending = this->PendingInterrupt(bus);
  });

  EXPECT_FALSE(interrupting);
  EXPECT_EQ(pending, this->kNonePending);
}

REGISTER_TYPED_TEST_SUITE_P(
    UartContract, BytesWrittenToTheTransmitRegisterBecomeTheOutput,
    AfterAByteIsWrittenTheLineStatusShowsTheTransmitterReady,
    WithTheDivisorLatchOpenTheFirstTwoRegistersHoldTheDivisor,
    WithTheDivisorLatchOpenNothingIsTransmitted,
    TheControlAndScratchRegistersReadBackWhatWasWritten,
    TheScratchRegisterIsSeenByADebugAccess,
    WithNothingReceivedTheLineStatusShowsNoDataReady,
    AByteThatComesInIsReadFromTheReceiveRegisterAndThenThereIsNone,
    BytesThatComeInAreReadInTheOrderTheyCameWithDataReadyUntilTheLast,
    BytesThatComeInWhileOthersWaitAreReadAfterThem,
    TheInterruptEnableRegisterReadsBackWhatWasWritten,
    WithTheReceiveInterruptEnabledAByteThatComesInInterruptsUntilItIsRead,
    EnablingTheReceiveInterruptWithAByteAlreadyWaitingInterrupts,
    WithTwoBytesWaitingReadingOneLeavesTheReceiveInterruptPending,
    ReadingTwoBytesOneStraightAfterTheOtherEndsTheInterrupt,
    EnablingTheTransmitInterruptWhileNothingIsBeingSentInterrupts,
    ReadingWhichInterruptIsPendingEndsTheTransmitInterrupt,
    RewritingTheEnableRegisterDoesNotRaiseTheTransmitInterruptAgain,
    WithTheTransmitInterruptEnabledWritingAByteInterruptsAgain,
    WithBothPendingAReceivedByteIsSaidFirstAndTheTransmitterAfterIt,
    DisablingTheTransmitInterruptWhileItIsPendingEndsIt,
    WithNoInterruptEnabledTheLineStaysLow);

#endif  // TESTS_CPP_CONTRACTS_UART_CONTRACT_H_
