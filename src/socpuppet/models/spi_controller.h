#ifndef SOCPUPPET_MODELS_SPI_CONTROLLER_H_
#define SOCPUPPET_MODELS_SPI_CONTROLLER_H_

#include <cstdint>
#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/spi_device.h"

namespace socpuppet {

// An SPI controller: the block a CPU talks to the chips on an SPI bus
// through, a byte at a time. It is the one in SiFive's FE310 and FU540,
// which Zephyr (`spi_sifive`) and Linux (`spi-sifive`) both drive.
//
// The model is borrowed: SiFive's SPI controller from VPV-Peripherals
// (Minres). This class is the adapter that fits it into a socpuppet
// platform: it gives the controller a clock, resets it as the simulation
// starts, and is the bus's wires, handing each byte to the SpiDevice whose
// chip select is low and its answer back.
class SpiController : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<SpiController> socket{"socket"};
  // The controller's interrupt, for its FIFOs' watermarks.
  sc_core::sc_out<bool> irq{"irq"};

  // `clock_hz` is the controller's clock, which SPI's is made from.
  SpiController(const sc_core::sc_module_name& name, std::uint64_t clock_hz);
  ~SpiController() override;

  // Puts `device` on the bus at `chip_select`, 0 to 3. It is not owned,
  // and must stay alive while the simulation runs.
  void Attach(unsigned chip_select, SpiDevice& device);

 private:
  struct Model;

  // Copies the borrowed model's interrupt output to `irq`.
  void DriveTheLine();

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay);
  std::unique_ptr<Model> model_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_SPI_CONTROLLER_H_
