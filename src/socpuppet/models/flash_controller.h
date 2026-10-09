#ifndef SOCPUPPET_MODELS_FLASH_CONTROLLER_H_
#define SOCPUPPET_MODELS_FLASH_CONTROLLER_H_

#include <cstdint>
#include <optional>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/flash_controller_logic.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/nand_port.h"
#include "socpuppet/models/nand_link.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

// The part of an SSD's controller that works the NAND flash chip. The
// SSD's CPU says which page and where it is in the SSD's own memory, and
// the controller moves it: from the chip into memory, or from memory into
// the chip. This is the SystemC wrapper, and the logic is in
// FlashControllerLogic.
//
// `cpu` is its register block, `local` is how it reads and writes the
// SSD's own memory, and `nand` is the chip.
//
// A write to the command register returns at once, and the command is
// carried out by a process of the controller's own, one delta cycle later
// at the same simulated time. Real hardware works alongside its CPU in the
// same way, and there is an engineering reason too: carrying a command out
// puts an access on the bus the CPU's own write is still crossing.
class FlashController : public sc_core::sc_module,
                        private NandPort,
                        private MemoryPort {
 public:
  tlm_utils::simple_target_socket<FlashController> cpu{"cpu"};
  tlm_utils::simple_initiator_socket<FlashController> local{"local"};
  tlm_utils::simple_initiator_socket<FlashController> nand{"nand"};
  sc_core::sc_out<bool> irq{"irq"};

  explicit FlashController(const sc_core::sc_module_name& name)
      : sc_module(name), logic_(*this, *this) {
    cpu.register_b_transport(this, &FlashController::b_transport);
    cpu.register_transport_dbg(this, &FlashController::transport_dbg);
    SC_THREAD(Work);
    SC_METHOD(DriveTheLine);
    sensitive << line_may_have_changed_;
    dont_initialize();
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    const bool ok = transaction.is_read()
                        ? logic_.ReadRegister(transaction.get_address(), data)
                        : logic_.WriteRegister(transaction.get_address(), data);
    transaction.set_response_status(ok ? tlm::TLM_OK_RESPONSE
                                       : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    if (transaction.is_write()) {
      line_may_have_changed_.notify();
      work_.notify(sc_core::SC_ZERO_TIME);
    }
  }

  // Debug transport: the registers as a debugger sees them, in no simulated
  // time. Returns the bytes transferred, which is none if nothing is there.
  // A debugger can look and cannot touch: a write is declined, because a
  // command given this way would be work the firmware never asked for.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    return transaction.is_read() &&
                   logic_.ReadRegister(transaction.get_address(), data)
               ? transaction.get_data_length()
               : 0;
  }

  void Work() {
    for (;;) {
      wait(work_);
      if (logic_.CarryOut()) line_may_have_changed_.notify();
    }
  }

  // The only process that writes the line. A SystemC signal takes one
  // writer, and both the CPU's access and the controller's own work change
  // what the line should say.
  void DriveTheLine() { irq.write(logic_.Interrupting()); }

  // NandPort: the chip.
  std::optional<NandGeometry> Geometry() override {
    return NandGeometryOf(nand);
  }
  bool ReadPage(std::uint32_t block, std::uint32_t page,
                std::span<std::uint8_t> out) override {
    return NandTransport(nand, NandCommand::Operation::kReadPage, block, page,
                         out) == tlm::TLM_OK_RESPONSE;
  }
  bool ProgramPage(std::uint32_t block, std::uint32_t page,
                   std::span<const std::uint8_t> in) override {
    return NandTransport(nand, NandCommand::Operation::kProgramPage, block,
                         page, WriteData(in)) == tlm::TLM_OK_RESPONSE;
  }
  bool EraseBlock(std::uint32_t block) override {
    return NandTransport(nand, NandCommand::Operation::kEraseBlock, block, 0,
                         {}) == tlm::TLM_OK_RESPONSE;
  }

  // MemoryPort: the SSD's own memory.
  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return Transport(local, tlm::TLM_READ_COMMAND, address, out) ==
           tlm::TLM_OK_RESPONSE;
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return Transport(local, tlm::TLM_WRITE_COMMAND, address, WriteData(in)) ==
           tlm::TLM_OK_RESPONSE;
  }

  FlashControllerLogic logic_;
  // Notified when the CPU has written to a register, which may have given
  // the controller something to do.
  sc_core::sc_event work_;
  // Notified when what the interrupt line should say may have changed.
  sc_core::sc_event line_may_have_changed_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_FLASH_CONTROLLER_H_
