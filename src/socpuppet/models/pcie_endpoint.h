#ifndef SOCPUPPET_MODELS_PCIE_ENDPOINT_H_
#define SOCPUPPET_MODELS_PCIE_ENDPOINT_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/pcie_endpoint_registers.h"
#include "socpuppet/models/pcie_link.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

// A PCIe endpoint: what stands between a PCIe link and a function, such as
// an NVMe controller, that knows nothing about PCIe. This is the SystemC
// wrapper, and the registers are in PcieEndpointRegisters.
//
//   the link                                     the function
//   from_host ──▶ configuration space
//             ──▶ memory accesses ─────────────▶ bar0
//   to_host   ◀── the function's DMA ◀────────── dma
//             ◀── interrupts, as messages ◀───── irq
class PcieEndpoint : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<PcieEndpoint> from_host{"from_host"};
  tlm_utils::simple_initiator_socket<PcieEndpoint> to_host{"to_host"};
  // The function's side: its register block, its DMA, and one interrupt
  // line for each vector.
  tlm_utils::simple_initiator_socket<PcieEndpoint> bar0{"bar0"};
  tlm_utils::simple_target_socket<PcieEndpoint> dma{"dma"};
  sc_core::sc_vector<sc_core::sc_in<bool>> irq;

  // `function_size` is how many bytes the function's register block takes,
  // and `vectors` how many interrupt lines it has.
  PcieEndpoint(const sc_core::sc_module_name& name,
               const PcieEndpointRegisters::Identity& identity,
               std::uint64_t function_size, std::size_t vectors)
      : sc_module(name),
        irq("irq", vectors),
        registers_(identity, function_size, vectors) {
    from_host.register_b_transport(this, &PcieEndpoint::FromHost);
    dma.register_b_transport(this, &PcieEndpoint::FromFunction);
    SC_METHOD(NoticeRisingLines);
    for (sc_core::sc_in<bool>& line : irq) sensitive << line.pos();
    dont_initialize();
    SC_THREAD(SendMessages);
  }

  // An interrupt line that nothing is connected to is tied low.
  void before_end_of_elaboration() override {
    for (sc_core::sc_in<bool>& line : irq) {
      if (line.size() == 0) line.bind(tied_low_);
    }
  }

 private:
  void FromHost(tlm::tlm_generic_payload& transaction,
                sc_core::sc_time& delay) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    if (IsConfigurationAccess(transaction)) {
      if (transaction.is_read()) {
        registers_.ReadConfiguration(transaction.get_address(), data);
      } else {
        registers_.WriteConfiguration(transaction.get_address(), data);
        SendWhatCanNowBeSent();
      }
      transaction.set_response_status(tlm::TLM_OK_RESPONSE);
      return;
    }
    // A memory access: the function's or the endpoint's own, if it is
    // inside where BAR0 points.
    const PcieEndpointRegisters::Landing landing =
        registers_.Decode(transaction.get_address(), data.size());
    switch (landing.owner) {
      case PcieEndpointRegisters::Owner::kNobody:
        transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
        return;
      case PcieEndpointRegisters::Owner::kFunction: {
        const std::uint64_t address_on_the_bus = transaction.get_address();
        transaction.set_address(landing.offset);
        bar0->b_transport(transaction, delay);
        transaction.set_address(address_on_the_bus);
        return;
      }
      case PcieEndpointRegisters::Owner::kTable:
      case PcieEndpointRegisters::Owner::kPendingBits:
        if (transaction.is_read()) {
          registers_.ReadOwn(landing, data);
        } else {
          registers_.WriteOwn(landing, data);
          SendWhatCanNowBeSent();
        }
        transaction.set_response_status(tlm::TLM_OK_RESPONSE);
        return;
    }
  }

  // The function's DMA goes up the link as it is, once the host has let
  // the device be a bus master.
  void FromFunction(tlm::tlm_generic_payload& transaction,
                    sc_core::sc_time& delay) {
    if (!registers_.IsBusMaster()) {
      transaction.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
      return;
    }
    to_host->b_transport(transaction, delay);
  }

  // An interrupt is the rise of one of the function's lines. Each rise
  // becomes one message, now or once the host unmasks the vector.
  void NoticeRisingLines() {
    for (std::size_t line = 0; line < irq.size(); ++line) {
      if (!irq[line].posedge()) continue;
      if (const auto message = registers_.Raise(line)) Post(*message);
    }
  }

  // A write from the host may have unmasked a vector that was waiting.
  void SendWhatCanNowBeSent() {
    for (const PcieEndpointRegisters::Message& message :
         registers_.TakePending()) {
      Post(message);
    }
  }

  void Post(const PcieEndpointRegisters::Message& message) {
    outbox_.push_back(message);
    send_.notify(sc_core::SC_ZERO_TIME);
  }

  // Messages go up the link from a process of the endpoint's own. A bus
  // access may have to wait its turn, which only a thread can do, and it
  // must not start from inside the host's access that unmasked a vector.
  void SendMessages() {
    for (;;) {
      wait(send_);
      while (!outbox_.empty()) {
        const PcieEndpointRegisters::Message message = outbox_.front();
        outbox_.pop_front();
        // An interrupt message is a 32-bit write of the vector's data to
        // its address, little-endian like everything on this bus.
        std::array<std::uint8_t, 4> data{};
        for (std::size_t index = 0; index < data.size(); ++index) {
          data[index] = static_cast<std::uint8_t>(message.data >> (8 * index));
        }
        if (Transport(to_host, tlm::TLM_WRITE_COMMAND, message.address, data) !=
            tlm::TLM_OK_RESPONSE) {
          registers_.NoteMasterAbort();
        }
      }
    }
  }

  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  PcieEndpointRegisters registers_;
  // Messages waiting to go up the link, oldest first.
  std::deque<PcieEndpointRegisters::Message> outbox_;
  sc_core::sc_event send_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_PCIE_ENDPOINT_H_
