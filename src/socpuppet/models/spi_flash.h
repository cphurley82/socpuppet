#ifndef SOCPUPPET_MODELS_SPI_FLASH_H_
#define SOCPUPPET_MODELS_SPI_FLASH_H_

#include <cstdint>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/spi_nor_chip.h"
#include "socpuppet/models/spi_controller.h"

namespace socpuppet {

// A flash chip and the SPI controller it is reached through: where a
// system keeps the firmware a CPU boots from.
//
// 🎓 A flash is read in two ways. A driver speaks SPI to it, a command and
// then an address a byte at a time, through the controller's registers
// (`socket`). And the controller maps the flash into the address space, so
// that it reads like memory and code can even run from it (execute in
// place, XIP): that is `xip`, and it is what a boot ROM uses, since a ROM
// has no room for an SPI driver.
//
// The controller is SiFive's, borrowed from VPV-Peripherals (Minres) as
// SpiController, and the chip is socpuppet's own, a SpiNorChip of
// Winbond's W25Q kind on the controller's first chip select. `xip` reads
// the chip's bytes straight, as a controller's memory-mapped mode does:
// it is for reading, it ends where the flash does, and a debugger's write
// through it is how a platform fills the flash.
class SpiFlash : public sc_core::sc_module {
 public:
  // The controller's registers.
  tlm::tlm_target_socket<> socket{"socket"};
  // The flash, read like memory.
  tlm_utils::simple_target_socket<SpiFlash> xip{"xip"};

  // `size` is how many bytes the flash holds: a power of two, as every
  // W25Q part's is.
  SpiFlash(const sc_core::sc_module_name& name, std::uint64_t size);

  // Puts `device` on the flash's SPI bus beside its chip, at `chip_select`,
  // 1 to 3: the chip is at 0. It is not owned, and must stay alive while
  // the simulation runs.
  void Attach(unsigned chip_select, SpiDevice& device);

 private:
  void WindowAccess(tlm::tlm_generic_payload& transaction,
                    sc_core::sc_time& delay);
  // Debug transport through the window: no simulated time. Returns the
  // bytes transferred.
  unsigned DebugWindowAccess(tlm::tlm_generic_payload& transaction);
  // Whether an access is inside the flash.
  bool Fits(const tlm::tlm_generic_payload& transaction);
  // Moves an access's bytes between it and the chip, which it fits.
  void Copy(tlm::tlm_generic_payload& transaction);

  SpiNorChip chip_;
  // The controller's interrupt is nobody's yet.
  sc_core::sc_signal<bool> interrupt_unread_{"interrupt_unread"};
  // After the chip, which it is handed and must not outlive.
  SpiController controller_{"controller"};
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_SPI_FLASH_H_
