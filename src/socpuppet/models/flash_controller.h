#ifndef SOCPUPPET_MODELS_FLASH_CONTROLLER_H_
#define SOCPUPPET_MODELS_FLASH_CONTROLLER_H_

#include <systemc>
#include <tlm_utils/simple_initiator_socket.h>

#include "socpuppet/core/flash_controller_logic.h"
#include "socpuppet/models/command_device.h"
#include "socpuppet/models/nand_link.h"
#include "socpuppet/models/socket_memory.h"

namespace socpuppet {

// The part of an SSD's controller that works the NAND flash chip. The
// SSD's CPU says which page and where it is in the SSD's own memory, and
// the controller moves it: from the chip into memory, or from memory into
// the chip. This is the SystemC wrapper, and the logic is in
// FlashControllerLogic.
//
// `cpu` is its register block and `irq` its interrupt line (see
// CommandDevice). `local` is how it reads and writes the SSD's own memory,
// and `nand` is the chip.
class FlashController : public CommandDevice<FlashControllerLogic> {
 public:
  tlm_utils::simple_initiator_socket<FlashController> local{"local"};
  tlm_utils::simple_initiator_socket<FlashController> nand{"nand"};

  explicit FlashController(const sc_core::sc_module_name& name)
      : CommandDevice(name, logic_) {}

 private:
  using Initiator = tlm_utils::simple_initiator_socket<FlashController>;

  // The chip and the SSD's own memory, as the logic reaches them.
  SocketNand<Initiator> chip_{nand};
  SocketMemory<Initiator> local_memory_{local};
  FlashControllerLogic logic_{chip_, local_memory_};
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_FLASH_CONTROLLER_H_
