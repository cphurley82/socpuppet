#ifndef SOCPUPPET_MODELS_IMSIC_H_
#define SOCPUPPET_MODELS_IMSIC_H_

#include <algorithm>
#include <cstdint>
#include <optional>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/interrupt_file.h"
#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/hart_registers.h"

namespace socpuppet {

// A RISC-V IMSIC: the interrupt controller that one hart is sent messages
// at.
//
// 🎓 An IMSIC (incoming message-signalled interrupt controller) is half of
// RISC-V's Advanced Interrupt Architecture. A device interrupts by writing
// a number, an interrupt identity, to an address, and that is all: no wire
// runs from the device to the hart. A PCIe device's interrupt is such a
// message already (MSI), and a device that only has a wire gets one sent
// for it by the other half, an APLIC.
//
// It keeps two interrupt files, one for machine mode and one for
// supervisor mode, so that an operating system and the monitor under it
// each have their own. A file has:
//   - a page on the bus, of 4 KiB, whose first 32 bits take a message: a
//     write of an identity makes it pending. That is all the page is for.
//     It reads as zero everywhere, and a write anywhere else in it does
//     nothing. It is read and written 32 bits at a time.
//   - registers, which are not on the bus at all. Firmware reaches them
//     through the hart, and so they are behind `csr` here
//     (models/hart_registers.h). They say which identities it wants to
//     hear of, and hand it the one to see to next.
//   - a line to the hart, high while an identity firmware wants is
//     pending: the machine or the supervisor external interrupt.
//
// What it leaves out: the page's second register, which takes a message
// with its bytes the other way round and here is one more place a write
// does nothing, the files a hypervisor's guests have, and what
// InterruptFile leaves out.
class Imsic : public sc_core::sc_module {
 public:
  // The pages messages are written to, for machine mode and for supervisor
  // mode.
  tlm_utils::simple_target_socket<Imsic> machine{"machine"};
  tlm_utils::simple_target_socket<Imsic> supervisor{"supervisor"};
  // The hart's way to the files' registers.
  tlm_utils::simple_target_socket<Imsic> csr{"csr"};
  // The machine external interrupt, for a CPU's `irq`, and the supervisor
  // external interrupt, for its `supervisor_irq`.
  sc_core::sc_out<bool> irq{"irq"};
  sc_core::sc_out<bool> supervisor_irq{"supervisor_irq"};

  // `identities` is the highest interrupt identity each file has.
  Imsic(const sc_core::sc_module_name& name, std::uint32_t identities)
      : sc_module(name),
        machine_file_(identities),
        supervisor_file_(identities) {
    machine.register_b_transport(this, &Imsic::MessageForMachineMode);
    supervisor.register_b_transport(this, &Imsic::MessageForSupervisorMode);
    csr.register_b_transport(this, &Imsic::HartAccess);
    SC_METHOD(DriveTheLines);
    sensitive << changed_;
    dont_initialize();
  }

 private:
  // Where on a page a message is written, and how wide it is. The AIA
  // specification calls the register seteipnum_le.
  static constexpr std::uint64_t kSeteipnumLe = 0x000;
  static constexpr unsigned kMessageBytes = 4;

  void MessageForMachineMode(tlm::tlm_generic_payload& transaction,
                             sc_core::sc_time&) {
    PageAccess(machine_file_, transaction);
  }
  void MessageForSupervisorMode(tlm::tlm_generic_payload& transaction,
                                sc_core::sc_time&) {
    PageAccess(supervisor_file_, transaction);
  }

  // A device's access to a file's page.
  void PageAccess(InterruptFile& file, tlm::tlm_generic_payload& transaction) {
    if (transaction.get_data_length() != kMessageBytes) {
      transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
      return;
    }
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    if (transaction.is_read()) {
      std::ranges::fill(data, std::uint8_t{0});
    } else if (transaction.get_address() == kSeteipnumLe) {
      file.Deliver(LoadLittleEndian<std::uint32_t>(data));
      changed_.notify();
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }

  // The hart's access to one of the registers it has from here.
  void HartAccess(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const bool answered =
        transaction.get_data_length() == kHartRegisterBytes &&
        Answer(transaction.get_address(), transaction.is_read(),
               {transaction.get_data_ptr(), transaction.get_data_length()});
    transaction.set_response_status(answered ? tlm::TLM_OK_RESPONSE
                                             : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    changed_.notify();
  }

  // Reads or writes the register at an address of the hart's, if there is
  // one there. Returns whether there is.
  bool Answer(std::uint64_t address, bool is_read,
              std::span<std::uint8_t> data) {
    switch (CsrOf(address)) {
      case kMireg:
        return WindowAccess(machine_file_, SelectedBy(address), is_read, data);
      case kSireg:
        return WindowAccess(supervisor_file_, SelectedBy(address), is_read,
                            data);
      case kMtopei:
        TopAccess(machine_file_, is_read, data);
        return true;
      case kStopei:
        TopAccess(supervisor_file_, is_read, data);
        return true;
      default:
        return false;
    }
  }

  // `mtopei` or `stopei`: a read is the file's top identity, and a write,
  // of anything, claims it. The register has the identity in bits 26 to
  // 16, and again in the low eleven as its priority, which with an IMSIC
  // is the same number.
  static void TopAccess(InterruptFile& file, bool is_read,
                        std::span<std::uint8_t> data) {
    if (is_read) {
      const std::uint64_t top = file.Top();
      StoreLittleEndian((top << 16U) | top, data);
    } else {
      file.Claim();
    }
  }

  // `mireg` or `sireg`: the register of the file's that was selected.
  // Returns whether the file has one of that number.
  static bool WindowAccess(InterruptFile& file, std::uint32_t selected,
                           bool is_read, std::span<std::uint8_t> data) {
    if (!is_read) {
      return file.Write(selected, LoadLittleEndian<std::uint64_t>(data));
    }
    const std::optional<std::uint64_t> value = file.Read(selected);
    if (value) StoreLittleEndian(*value, data);
    return value.has_value();
  }

  // The only process that writes the lines. A message arrives in the
  // sending device's process and a register is written in the hart's, and
  // a SystemC signal takes one writer.
  void DriveTheLines() {
    irq.write(machine_file_.Interrupting());
    supervisor_irq.write(supervisor_file_.Interrupting());
  }

  InterruptFile machine_file_;
  InterruptFile supervisor_file_;
  sc_core::sc_event changed_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_IMSIC_H_
