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

// Asks the chip what it is, with room for `out.size()` bytes of answer.
inline tlm::tlm_response_status AskGeometry(BusDriver& controller,
                                            std::span<std::uint8_t> out) {
  return socpuppet::NandTransport(controller.socket,
                                  socpuppet::NandCommand::Operation::kGeometry,
                                  0, 0, out);
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
  const socpuppet::NandGeometry geometry =
      said.value_or(socpuppet::NandGeometry{});
  EXPECT_EQ(geometry.page_size, 16U);
  EXPECT_EQ(geometry.pages_per_block, 8U);
  EXPECT_EQ(geometry.blocks, 4U);
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
  tlm::tlm_response_status programmed_first = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status programmed_last = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    programmed_first =
        nand_contract::ProgramPage(controller, 2, 0, nand_contract::SomePage());
    programmed_last =
        nand_contract::ProgramPage(controller, 2, 7, nand_contract::SomePage());
    response = nand_contract::EraseBlock(controller, 2);
    nand_contract::ReadPage(controller, 2, 0, first);
    nand_contract::ReadPage(controller, 2, 7, last);
  });

  ASSERT_EQ(programmed_first, tlm::TLM_OK_RESPONSE);
  ASSERT_EQ(programmed_last, tlm::TLM_OK_RESPONSE);
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

TYPED_TEST_P(NandContract, DataThatIsNotOnePageLongGetsABurstError) {
  std::vector<std::uint8_t> too_short(15, 0x11);
  std::vector<std::uint8_t> too_long(17, 0x22);
  std::vector<std::uint8_t> afterwards(16);
  std::vector<tlm::tlm_response_status> responses;

  this->AsItsController([&](BusDriver& controller) {
    responses = {nand_contract::ReadPage(controller, 0, 0, too_short),
                 nand_contract::ReadPage(controller, 0, 0, too_long),
                 nand_contract::ProgramPage(controller, 0, 0, too_short),
                 nand_contract::ProgramPage(controller, 0, 0, too_long)};
    nand_contract::ReadPage(controller, 0, 0, afterwards);
  });

  EXPECT_EQ(responses, std::vector<tlm::tlm_response_status>(
                           4, tlm::TLM_BURST_ERROR_RESPONSE));
  EXPECT_EQ(afterwards, std::vector<std::uint8_t>(16, 0xFF));
}

// A plain bus access, with nothing to say what is asked of the chip: what
// arrives if a chip is wired to a bus by mistake.
TYPED_TEST_P(NandContract, AnAccessThatIsNotACommandForAChipGetsACommandError) {
  std::vector<std::uint8_t> data(16);
  tlm::tlm_response_status read_response = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status write_response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    read_response = controller.Read(0, data);
    write_response = controller.Write(0, data);
  });

  EXPECT_EQ(read_response, tlm::TLM_COMMAND_ERROR_RESPONSE);
  EXPECT_EQ(write_response, tlm::TLM_COMMAND_ERROR_RESPONSE);
}

TYPED_TEST_P(NandContract,
             AnAnswerAboutGeometryThatWouldNotFitGetsABurstError) {
  std::vector<std::uint8_t> too_short(socpuppet::kNandGeometryBytes - 1);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    response = nand_contract::AskGeometry(controller, too_short);
  });

  EXPECT_EQ(response, tlm::TLM_BURST_ERROR_RESPONSE);
}

// A chip is not memory: there is nothing a debugger's read of an address
// could mean to it.
TYPED_TEST_P(NandContract, ADebugAccessIsDeclined) {
  std::vector<std::uint8_t> data(16);
  unsigned bytes_read = 1;
  unsigned bytes_written = 1;

  this->AsItsController([&](BusDriver& controller) {
    bytes_read = controller.DebugRead(0, data);
    bytes_written = controller.DebugWrite(0, data);
  });

  EXPECT_EQ(bytes_read, 0U);
  EXPECT_EQ(bytes_written, 0U);
}

TYPED_TEST_P(NandContract, APageOfAnErasedBlockCanBeProgrammedAgain) {
  std::vector<std::uint8_t> read(16);
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    nand_contract::ProgramPage(controller, 2, 5, nand_contract::SomePage(10));
    nand_contract::EraseBlock(controller, 2);
    response = nand_contract::ProgramPage(controller, 2, 5,
                                          nand_contract::SomePage(20));
    nand_contract::ReadPage(controller, 2, 5, read);
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(read, nand_contract::SomePage(20));
}

TYPED_TEST_P(NandContract, ErasingABlockLeavesTheBlocksAroundItAlone) {
  std::vector<std::uint8_t> in_the_block_before(16);
  std::vector<std::uint8_t> in_the_block_after(16);
  tlm::tlm_response_status erased = tlm::TLM_INCOMPLETE_RESPONSE;

  this->AsItsController([&](BusDriver& controller) {
    nand_contract::ProgramPage(controller, 1, 7, nand_contract::SomePage(10));
    nand_contract::ProgramPage(controller, 3, 0, nand_contract::SomePage(20));
    erased = nand_contract::EraseBlock(controller, 2);
    nand_contract::ReadPage(controller, 1, 7, in_the_block_before);
    nand_contract::ReadPage(controller, 3, 0, in_the_block_after);
  });

  ASSERT_EQ(erased, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(in_the_block_before, nand_contract::SomePage(10));
  EXPECT_EQ(in_the_block_after, nand_contract::SomePage(20));
}

REGISTER_TYPED_TEST_SUITE_P(NandContract, AChipAskedWhatItIsSaysItsGeometry,
                            APageThatWasNeverProgrammedReadsAsAllOnes,
                            AProgrammedPageReadsBackAsItWasProgrammed,
                            EveryPageOfAnErasedBlockReadsAsAllOnes,
                            ABlockPastTheEndOfTheChipGetsAnAddressError,
                            APagePastTheEndOfItsBlockGetsAnAddressError,
                            DataThatIsNotOnePageLongGetsABurstError,
                            AnAccessThatIsNotACommandForAChipGetsACommandError,
                            AnAnswerAboutGeometryThatWouldNotFitGetsABurstError,
                            ADebugAccessIsDeclined,
                            APageOfAnErasedBlockCanBeProgrammedAgain,
                            ErasingABlockLeavesTheBlocksAroundItAlone);

#endif  // TESTS_CPP_CONTRACTS_NAND_CONTRACT_H_
