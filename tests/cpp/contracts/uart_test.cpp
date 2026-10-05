#include "socpuppet/models/ns16550.h"
#include "tests/cpp/contracts/uart_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Ns16550, UartContract,
                               ::testing::Types<socpuppet::Ns16550>);
