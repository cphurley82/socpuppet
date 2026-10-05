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

REGISTER_TYPED_TEST_SUITE_P(UartContract,
                            BytesWrittenToTheTransmitRegisterBecomeTheOutput);

#endif  // TESTS_CPP_CONTRACTS_UART_CONTRACT_H_
