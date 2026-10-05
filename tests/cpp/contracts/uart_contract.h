#ifndef TESTS_CPP_CONTRACTS_UART_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_UART_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/platform/slots.h"
#include "tests/cpp/contracts/bus_driver.h"

// What every 16550-style UART must do, whatever is behind it. This is the
// part of the 16550 that a driver's polled console relies on.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, UartContract,
//                                  ::testing::Types<MyUart>);
// MyUart must fit the UART slot (see socpuppet/platform/slots.h).
template <socpuppet::UartSlot UartType>
class UartContract : public ::testing::Test {
 protected:
  // The 16550's registers, one byte each, by their offset.
  static constexpr std::uint64_t kTransmitHolding = 0;
  // With the divisor latch open, the first two registers are the divisor
  // that sets the baud rate, low byte first.
  static constexpr std::uint64_t kDivisorLow = 0;
  static constexpr std::uint64_t kDivisorHigh = 1;
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

  // Not a value any test expects, so that a read the UART leaves unanswered
  // shows.
  static constexpr std::uint8_t kUnanswered = 0xA5;

  // Runs `body` in a simulation thread wired to the UART, to completion.
  void OnTheBus(std::function<void(BusDriver&)> body) {
    BusDriver driver{"driver", std::move(body)};
    driver.socket.bind(uart_.socket);
    sc_core::sc_start();
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

  UartType uart_{"uart"};
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

TYPED_TEST_P(UartContract, WithNothingReceivedTheLineStatusShowsNoDataReady) {
  std::uint8_t status = this->kDataReady;

  this->OnTheBus([&](BusDriver& bus) {
    status = this->ReadRegister(bus, this->kLineStatus);
  });

  EXPECT_EQ(status & this->kDataReady, 0);
}

REGISTER_TYPED_TEST_SUITE_P(
    UartContract, BytesWrittenToTheTransmitRegisterBecomeTheOutput,
    AfterAByteIsWrittenTheLineStatusShowsTheTransmitterReady,
    WithTheDivisorLatchOpenTheFirstTwoRegistersHoldTheDivisor,
    WithTheDivisorLatchOpenNothingIsTransmitted,
    TheControlAndScratchRegistersReadBackWhatWasWritten,
    WithNothingReceivedTheLineStatusShowsNoDataReady);

#endif  // TESTS_CPP_CONTRACTS_UART_CONTRACT_H_
