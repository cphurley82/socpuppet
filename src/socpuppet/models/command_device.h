#ifndef SOCPUPPET_MODELS_COMMAND_DEVICE_H_
#define SOCPUPPET_MODELS_COMMAND_DEVICE_H_

#include <concepts>
#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// What the logic of such a device has to offer its shell (below): reads and
// writes of its register block, each saying whether the access was taken,
// the carrying out of the command it was last given, which says whether
// there was one, and whether it is asking for its CPU's attention.
template <typename T>
concept CommandLogic =
    requires(T logic, const T looked_at, std::uint64_t offset,
             std::span<std::uint8_t> out, std::span<const std::uint8_t> in) {
      { looked_at.ReadRegister(offset, out) } -> std::same_as<bool>;
      { logic.WriteRegister(offset, in) } -> std::same_as<bool>;
      { logic.CarryOut() } -> std::same_as<bool>;
      { looked_at.Interrupting() } -> std::same_as<bool>;
    };

// The SystemC shell of a device that its CPU gives one command at a time,
// through a register block: the flash controller and the DMA engine of an
// SSD. What the registers mean and what a command does is the device's
// `Logic`, a plain C++ class. The shell is what is the same for all of
// them: when the work is done, who drives the interrupt line, and what a
// debugger may do. A device derives from this and adds the sockets its
// work goes out through.
//
// A write to a register returns at once, and a command is carried out by a
// process of the device's own, one delta cycle later at the same simulated
// time. (A delta cycle is one round of the simulator letting every process
// that is ready run, with no time passing.) Real hardware works alongside
// its CPU in the same way, and there is an engineering reason too: carrying
// a command out puts an access on the bus the CPU's own write is still
// crossing.
template <CommandLogic Logic>
class CommandDevice : public sc_core::sc_module {
 public:
  // The register block.
  tlm_utils::simple_target_socket<CommandDevice> cpu{"cpu"};
  // High while the device has something to tell the CPU that the CPU asked
  // to be told.
  sc_core::sc_out<bool> irq{"irq"};

 protected:
  // `logic` is the deriving device's own member. It is only used once the
  // device has been built, so it need not have been constructed yet.
  CommandDevice(const sc_core::sc_module_name& name, Logic& logic)
      : sc_module(name), logic_(logic) {
    cpu.register_b_transport(this, &CommandDevice::b_transport);
    cpu.register_transport_dbg(this, &CommandDevice::transport_dbg);
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
  // writer, and both the CPU's access and the device's own work change
  // what the line should say.
  void DriveTheLine() { irq.write(logic_.Interrupting()); }

  Logic& logic_;
  // Notified when the CPU has written to a register, which may have given
  // the device something to do.
  sc_core::sc_event work_;
  // Notified when what the interrupt line should say may have changed.
  sc_core::sc_event line_may_have_changed_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_COMMAND_DEVICE_H_
