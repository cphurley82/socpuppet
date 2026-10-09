#ifndef SOCPUPPET_MODELS_NAND_LINK_H_
#define SOCPUPPET_MODELS_NAND_LINK_H_

#include <array>
#include <cstdint>
#include <optional>
#include <span>

#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/nand_array.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

// How a flash controller talks to a NAND chip: a pair of ordinary TLM
// sockets, with this extension on every transaction to say what is asked
// of the chip. A real chip is told by command, address and data cycles on
// its pins. What a controller's firmware can observe of that is which
// operation was asked for, of which page, and how it came out, so that is
// what is kept here.
//
// The transaction's data is the page for a read or a program, nothing for
// an erase, and three 32-bit numbers for the geometry. Its own address
// means nothing. A read of a page or of the geometry is a TLM read, and a
// program or an erase is a TLM write.
struct NandCommand : tlm::tlm_extension<NandCommand> {
  enum class Operation {
    kReadPage,
    kProgramPage,
    kEraseBlock,
    // What the chip is: how big a page is, how many make a block, and how
    // many blocks there are. A real chip has a parameter page that says.
    kGeometry,
  };

  Operation operation = Operation::kGeometry;
  std::uint32_t block = 0;
  std::uint32_t page = 0;

  tlm::tlm_extension_base* clone() const override {
    return new NandCommand(*this);
  }
  void copy_from(const tlm::tlm_extension_base& other) override {
    *this = static_cast<const NandCommand&>(other);
  }
};

// The command a transaction carries, or nothing if it is not one for a
// NAND chip at all.
inline const NandCommand* NandCommandOf(
    const tlm::tlm_generic_payload& transaction) {
  const NandCommand* command = nullptr;
  transaction.get_extension(command);
  return command;
}

// How many bytes a chip's answer about its geometry is.
inline constexpr std::size_t kNandGeometryBytes = 12;

// One operation on the chip behind `socket`, and the chip's response.
template <typename Socket>
tlm::tlm_response_status NandTransport(Socket& socket,
                                       NandCommand::Operation operation,
                                       std::uint32_t block, std::uint32_t page,
                                       std::span<std::uint8_t> data) {
  const bool reads = operation == NandCommand::Operation::kReadPage ||
                     operation == NandCommand::Operation::kGeometry;
  tlm::tlm_generic_payload transaction;
  SetUpAccess(transaction,
              reads ? tlm::TLM_READ_COMMAND : tlm::TLM_WRITE_COMMAND, 0, data);
  NandCommand command;
  command.operation = operation;
  command.block = block;
  command.page = page;
  transaction.set_extension(&command);
  sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
  socket->b_transport(transaction, delay);
  transaction.clear_extension(&command);
  return transaction.get_response_status();
}

// Asks the chip behind `socket` what it is. Nothing, if it would not say.
template <typename Socket>
std::optional<NandGeometry> NandGeometryOf(Socket& socket) {
  std::array<std::uint8_t, kNandGeometryBytes> answer{};
  if (NandTransport(socket, NandCommand::Operation::kGeometry, 0, 0, answer) !=
      tlm::TLM_OK_RESPONSE) {
    return std::nullopt;
  }
  const std::span<const std::uint8_t> bytes{answer};
  return NandGeometry{
      .page_size = LoadLittleEndian<std::uint32_t>(bytes.subspan(0)),
      .pages_per_block = LoadLittleEndian<std::uint32_t>(bytes.subspan(4)),
      .blocks = LoadLittleEndian<std::uint32_t>(bytes.subspan(8))};
}

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_NAND_LINK_H_
