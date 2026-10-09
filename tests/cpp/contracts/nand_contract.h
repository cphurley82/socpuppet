#ifndef TESTS_CPP_CONTRACTS_NAND_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_NAND_CONTRACT_H_

#include <cstdint>
#include <functional>
#include <optional>
#include <span>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/nand_array.h"
#include "socpuppet/models/nand_link.h"
#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"

namespace nand_contract {

// The operations a controller asks of a chip, and the chip's response.
inline tlm::tlm_response_status ReadPage(BusDriver& controller,
                                         std::uint32_t block,
                                         std::uint32_t page,
                                         std::span<std::uint8_t> out) {
  return socpuppet::NandTransport(controller.socket,
                                  socpuppet::NandCommand::Operation::kReadPage,
                                  block, page, out);
}

inline tlm::tlm_response_status ProgramPage(BusDriver& controller,
                                            std::uint32_t block,
                                            std::uint32_t page,
                                            std::span<const std::uint8_t> in) {
  return socpuppet::NandTransport(
      controller.socket, socpuppet::NandCommand::Operation::kProgramPage, block,
      page, socpuppet::WriteData(in));
}

inline tlm::tlm_response_status EraseBlock(BusDriver& controller,
                                           std::uint32_t block) {
  return socpuppet::NandTransport(
      controller.socket, socpuppet::NandCommand::Operation::kEraseBlock, block,
      0, {});
}

// A page of data for the contract's chip, in which no two neighbouring
// bytes are the same.
inline std::vector<std::uint8_t> SomePage(std::uint8_t first_byte = 1) {
  std::vector<std::uint8_t> data(16);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(first_byte + index);
  }
  return data;
}

}  // namespace nand_contract

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

// The buffer does not start out as ones, so that a page the chip leaves
// untouched is not taken for an erased one.
TYPED_TEST_P(NandContract, APageThatWasNeverProgrammedReadsAsAllOnes) {
  std::vector<std::uint8_t> read(16, 0xA5);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    response = nand_contract::ReadPage(controller, 2, 5, read);
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(read, std::vector<std::uint8_t>(16, 0xFF));
}

TYPED_TEST_P(NandContract, AProgrammedPageReadsBackAsItWasProgrammed) {
  std::vector<std::uint8_t> read(16);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    response =
        nand_contract::ProgramPage(controller, 2, 5, nand_contract::SomePage());
    nand_contract::ReadPage(controller, 2, 5, read);
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(read, nand_contract::SomePage());
}

TYPED_TEST_P(NandContract, EveryPageOfAnErasedBlockReadsAsAllOnes) {
  std::vector<std::uint8_t> first(16);
  std::vector<std::uint8_t> last(16);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    nand_contract::ProgramPage(controller, 2, 0, nand_contract::SomePage());
    nand_contract::ProgramPage(controller, 2, 7, nand_contract::SomePage());
    response = nand_contract::EraseBlock(controller, 2);
    nand_contract::ReadPage(controller, 2, 0, first);
    nand_contract::ReadPage(controller, 2, 7, last);
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(first, std::vector<std::uint8_t>(16, 0xFF));
  EXPECT_EQ(last, std::vector<std::uint8_t>(16, 0xFF));
}

TYPED_TEST_P(NandContract, ABlockPastTheEndOfTheChipGetsAnAddressError) {
  std::vector<std::uint8_t> read(16);
  tlm::tlm_response_status read_response = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status program_response = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status erase_response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    read_response = nand_contract::ReadPage(controller, 4, 0, read);
    program_response =
        nand_contract::ProgramPage(controller, 4, 0, nand_contract::SomePage());
    erase_response = nand_contract::EraseBlock(controller, 4);
  });

  EXPECT_EQ(read_response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(program_response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(erase_response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

// Page 8 of block 0 would be the first page of block 1, if pages were
// simply counted through the chip.
TYPED_TEST_P(NandContract, APagePastTheEndOfItsBlockGetsAnAddressError) {
  std::vector<std::uint8_t> read(16);
  std::vector<std::uint8_t> first_of_the_next_block(16);
  tlm::tlm_response_status read_response = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status program_response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    read_response = nand_contract::ReadPage(controller, 0, 8, read);
    program_response =
        nand_contract::ProgramPage(controller, 0, 8, nand_contract::SomePage());
    nand_contract::ReadPage(controller, 1, 0, first_of_the_next_block);
  });

  EXPECT_EQ(read_response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(program_response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(first_of_the_next_block, std::vector<std::uint8_t>(16, 0xFF));
}

REGISTER_TYPED_TEST_SUITE_P(NandContract, AChipAskedWhatItIsSaysItsGeometry,
                            APageThatWasNeverProgrammedReadsAsAllOnes,
                            AProgrammedPageReadsBackAsItWasProgrammed,
                            EveryPageOfAnErasedBlockReadsAsAllOnes,
                            ABlockPastTheEndOfTheChipGetsAnAddressError,
                            APagePastTheEndOfItsBlockGetsAnAddressError);

#endif  // TESTS_CPP_CONTRACTS_NAND_CONTRACT_H_
