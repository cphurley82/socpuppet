#ifndef SOCPUPPET_MODELS_IDEAL_NAND_H_
#define SOCPUPPET_MODELS_IDEAL_NAND_H_

#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/nand_array.h"
#include "socpuppet/models/nand_link.h"

namespace socpuppet {

// A NAND flash chip that is easier to live with than a real one: nothing
// takes any time, and a page can be programmed again without erasing its
// block first.
class IdealNand : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<IdealNand> socket{"socket"};

  IdealNand(const sc_core::sc_module_name& name, const NandGeometry& geometry)
      : sc_module(name), array_(geometry) {
    socket.register_b_transport(this, &IdealNand::b_transport);
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const std::span<std::uint8_t> data{transaction.get_data_ptr(),
                                       transaction.get_data_length()};
    transaction.set_response_status(
        CarryOut(*NandCommandOf(transaction), data));
  }

  tlm::tlm_response_status CarryOut(const NandCommand& command,
                                    std::span<std::uint8_t> data) {
    switch (command.operation) {
      case NandCommand::Operation::kReadPage:
        array_.ReadPage(command.block, command.page, data);
        return tlm::TLM_OK_RESPONSE;
      case NandCommand::Operation::kProgramPage:
        array_.ProgramPage(command.block, command.page, data);
        return tlm::TLM_OK_RESPONSE;
      case NandCommand::Operation::kEraseBlock:
        array_.EraseBlock(command.block);
        return tlm::TLM_OK_RESPONSE;
      default:
        return SayGeometry(data);
    }
  }

  tlm::tlm_response_status SayGeometry(std::span<std::uint8_t> data) const {
    const NandGeometry& geometry = array_.geometry();
    StoreLittleEndian(geometry.page_size, data.subspan(0));
    StoreLittleEndian(geometry.pages_per_block, data.subspan(4));
    StoreLittleEndian(geometry.blocks, data.subspan(8));
    return tlm::TLM_OK_RESPONSE;
  }

  NandArray array_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_IDEAL_NAND_H_
