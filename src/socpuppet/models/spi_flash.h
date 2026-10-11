#ifndef SOCPUPPET_MODELS_SPI_FLASH_H_
#define SOCPUPPET_MODELS_SPI_FLASH_H_

#include <cstdint>
#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

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
// Both are borrowed: the SPI controller and the flash chip from
// VPV-Peripherals (Minres), joined by SCC's SPI channel. This class is the
// adapter that fits the three into a socpuppet platform. `xip` is its own:
// it is for reading, it ends where the flash does, and a debugger's write
// through it is how a platform fills the flash.
class SpiFlash : public sc_core::sc_module {
 public:
  // The controller's registers.
  tlm_utils::simple_target_socket<SpiFlash> socket{"socket"};
  // The flash, read like memory.
  tlm_utils::simple_target_socket<SpiFlash> xip{"xip"};

  // `size` is how many bytes the flash holds, up to the borrowed chip's
  // 256 MiB.
  SpiFlash(const sc_core::sc_module_name& name, std::uint64_t size);
  ~SpiFlash() override;

 private:
  struct Model;

  void RegisterAccess(tlm::tlm_generic_payload& transaction,
                      sc_core::sc_time& delay);
  void WindowAccess(tlm::tlm_generic_payload& transaction,
                    sc_core::sc_time& delay);
  // Debug transport through the window: no simulated time. Returns the
  // bytes transferred.
  unsigned DebugWindowAccess(tlm::tlm_generic_payload& transaction);
  // Whether an access is inside the flash.
  bool Fits(const tlm::tlm_generic_payload& transaction) const;

  std::uint64_t size_;
  std::unique_ptr<Model> model_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_SPI_FLASH_H_
