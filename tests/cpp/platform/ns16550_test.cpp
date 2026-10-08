#include "socpuppet/models/ns16550.h"

#include <array>
#include <cstdint>

#include <gtest/gtest.h>
#include <systemc>

#include "tests/cpp/support/bus_driver.h"

// What is the Ns16550's alone. What every UART must do is in the UART
// contract (tests/cpp/contracts/uart_contract.h).

// A real 16550 promises nothing about a receive register with nothing in
// it. The borrowed model would read a byte nobody had set, so the adapter
// gives the read a value.
TEST(WhenTheNs16550sReceiveRegisterIsReadWithNothingReceived, ItReadsAsZero) {
  socpuppet::Ns16550 uart{"uart"};
  std::array<std::uint8_t, 1> received{0xFF};
  BusDriver driver{"driver",
                   [&](BusDriver& bus) { bus.Read(/*address=*/0, received); }};
  driver.socket.bind(uart.socket);

  sc_core::sc_start();

  EXPECT_EQ(received[0], 0);
}
