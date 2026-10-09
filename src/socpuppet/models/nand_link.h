#ifndef SOCPUPPET_MODELS_NAND_LINK_H_
#define SOCPUPPET_MODELS_NAND_LINK_H_

#include <array>
#include <cstdint>
#include <optional>
#include <span>

#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/nand_geometry.h"
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
// means nothing. A read of a page or of the geometry is a TLM read and a
// program is a TLM write. An erase has no data to read or write, so it is
// TLM's third command, the one that says "see the extension".
struct NandCommand : tlm::tlm_extension<NandCommand> {
  enum class Operation {
    kReadPage,
    kProgramPage,
    kEraseBlock,
    // What the chip is: how big a page is, how many make a block, and how
    // many blocks there are. A real chip has a parameter page that says.
    kGeometry,
  };

  NandCommand(Operation the_operation, std::uint32_t the_block,
              std::uint32_t the_page)
      : operation(the_operation), block(the_block), page(the_page) {}

  Operation operation;
  // Which block, and which page of it. An erase is of a whole block, and
  // the geometry is of the whole chip.
  std::uint32_t block;
  std::uint32_t page;

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

// Makes a transaction a command for a chip for as long as this is alive:
// send it meanwhile. The transaction is the caller's again afterwards,
// however the sending ended.
class AsNandCommand {
 public:
  AsNandCommand(tlm::tlm_generic_payload& transaction,
                NandCommand::Operation operation, std::uint32_t block,
                std::uint32_t page)
      : transaction_(transaction), command_(operation, block, page) {
    transaction_.set_extension(&command_);
  }
  ~AsNandCommand() { transaction_.clear_extension(&command_); }
  AsNandCommand(const AsNandCommand&) = delete;
  AsNandCommand& operator=(const AsNandCommand&) = delete;

 private:
  tlm::tlm_generic_payload& transaction_;
  NandCommand command_;
};

// A chip's answer about its geometry: three 32-bit numbers, least
// significant byte first. The page size, the pages in a block, the blocks.
inline constexpr std::size_t kNandGeometryBytes = 12;

inline void StoreNandGeometry(const NandGeometry& geometry,
                              std::span<std::uint8_t> answer) {
  StoreLittleEndian(geometry.page_size, answer.subspan(0));
  StoreLittleEndian(geometry.pages_per_block, answer.subspan(4));
  StoreLittleEndian(geometry.blocks, answer.subspan(8));
}

inline NandGeometry LoadNandGeometry(std::span<const std::uint8_t> answer) {
  return NandGeometry{
      .page_size = LoadLittleEndian<std::uint32_t>(answer.subspan(0)),
      .pages_per_block = LoadLittleEndian<std::uint32_t>(answer.subspan(4)),
      .blocks = LoadLittleEndian<std::uint32_t>(answer.subspan(8))};
}

// Which of TLM's commands carries an operation.
inline tlm::tlm_command TlmCommandFor(NandCommand::Operation operation) {
  switch (operation) {
    case NandCommand::Operation::kReadPage:
    case NandCommand::Operation::kGeometry:
      return tlm::TLM_READ_COMMAND;
    case NandCommand::Operation::kProgramPage:
      return tlm::TLM_WRITE_COMMAND;
    case NandCommand::Operation::kEraseBlock:
      break;
  }
  return tlm::TLM_IGNORE_COMMAND;
}

// One operation on the chip behind `socket`, and the chip's response.
template <typename Socket>
tlm::tlm_response_status NandTransport(Socket& socket,
                                       NandCommand::Operation operation,
                                       std::uint32_t block, std::uint32_t page,
                                       std::span<std::uint8_t> data) {
  tlm::tlm_generic_payload transaction;
  SetUpAccess(transaction, TlmCommandFor(operation), 0, data);
  // TLM wants a streaming width of something, even with no data.
  if (data.empty()) transaction.set_streaming_width(1);
  const AsNandCommand as_command{transaction, operation, block, page};
  sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
  socket->b_transport(transaction, delay);
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
  return LoadNandGeometry(answer);
}

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_NAND_LINK_H_
