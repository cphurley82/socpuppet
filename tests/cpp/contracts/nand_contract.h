#ifndef TESTS_CPP_CONTRACTS_NAND_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_NAND_CONTRACT_H_

#include <cstdint>
#include <functional>
#include <optional>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/nand_array.h"
#include "socpuppet/models/nand_link.h"
#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"

// What every NAND flash chip must do, the ideal one and any more like the
// real thing: what a flash controller relies on, whichever is behind it.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, NandContract,
//                                  ::testing::Types<MyNand>);
// MyNand must fit the NAND slot (see socpuppet/platform/slots.h).
template <socpuppet::NandSlot NandType>
class NandContract : public ::testing::Test {
 protected:
  // A small chip: 4 blocks of 8 pages, each page 16 bytes.
  static constexpr socpuppet::NandGeometry kGeometry{
      .page_size = 16, .pages_per_block = 8, .blocks = 4};

  // Runs `body` in a simulation thread wired to the chip, to completion.
  // The body talks to the chip through the driver's socket.
  void AsItsController(std::function<void(BusDriver&)> body) {
    BusDriver driver{"controller", std::move(body)};
    driver.socket.bind(nand_.socket);
    sc_core::sc_start();
  }

  NandType nand_{"nand", kGeometry};
};

TYPED_TEST_SUITE_P(NandContract);

TYPED_TEST_P(NandContract, AChipAskedWhatItIsSaysItsGeometry) {
  std::optional<socpuppet::NandGeometry> said;

  this->AsItsController([&](BusDriver& controller) {
    said = socpuppet::NandGeometryOf(controller.socket);
  });

  ASSERT_TRUE(said.has_value());
  EXPECT_EQ(said->page_size, 16U);
  EXPECT_EQ(said->pages_per_block, 8U);
  EXPECT_EQ(said->blocks, 4U);
}

REGISTER_TYPED_TEST_SUITE_P(NandContract, AChipAskedWhatItIsSaysItsGeometry);

#endif  // TESTS_CPP_CONTRACTS_NAND_CONTRACT_H_
