#include <array>
#include <cstdint>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/models/ns16550.h"
#include "tests/cpp/contracts/bus_driver.h"
#include "tests/cpp/contracts/uart_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Ns16550, UartContract,
                               ::testing::Types<socpuppet::Ns16550>);

// Not part of the contract: a real 16550 promises nothing about a receive
// register with nothing in it. The borrowed model would read a byte nobody
// had set, so the adapter gives the read a value.
TEST(WhenTheNs16550sReceiveRegisterIsReadWithNothingReceived, ItReadsAsZero) {
  socpuppet::Ns16550 uart{"uart"};
  std::array<std::uint8_t, 1> received{0xFF};
  BusDriver driver{"driver",
                   [&](BusDriver& bus) { bus.Read(/*address=*/0, received); }};
  driver.socket.bind(uart.socket);

  sc_core::sc_start();

  EXPECT_EQ(received[0], 0);
}
