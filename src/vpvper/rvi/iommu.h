/*
 * Copyright (c) 2026 socpuppet contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef _RVI_IOMMU_H_
#define _RVI_IOMMU_H_

#include "iommu_walker.h"

#include <memory>
#include <scc/tlm_target.h>
#include <scc/utilities.h>
#include <tlm/scc/initiator_mixin.h>
#include <tlm/scc/target_mixin.h>

namespace vpvper {
namespace rvi {

class iommu_regs;

// which device a transaction that comes in to be translated is from: what the RISC-V IOMMU specification calls its
// device_id, a PCIe device's requester ID say
struct iommu_device_id : tlm::tlm_extension<iommu_device_id> {
    explicit iommu_device_id(uint32_t device)
    : id(device) {}
    tlm::tlm_extension_base* clone() const override { return new iommu_device_id(*this); }
    void copy_from(tlm::tlm_extension_base const& other) override { id = static_cast<iommu_device_id const&>(other).id; }

    uint32_t id;
};

// an IOMMU as the RISC-V IOMMU specification describes it, the subset that drivers use: a device directory of one to
// three levels and a first stage of Sv39, the command and fault queues, and a wired interrupt
class iommu : public sc_core::sc_module, public scc::tlm_target<> {
public:
    sc_core::sc_in<bool> rst_i{"rst_i"};
    // what devices send, to be translated: each transaction says which device sent it with an iommu_device_id
    tlm::scc::target_mixin<tlm::tlm_target_socket<scc::LT>> dma_i{"dma_i"};
    // what was translated, and the IOMMU's own reads and writes of memory
    tlm::scc::initiator_mixin<tlm::tlm_initiator_socket<scc::LT>> dma_o{"dma_o"};
    // the wired interrupt
    sc_core::sc_out<bool> irq_o{"irq_o"};

    iommu(sc_core::sc_module_name nm);
    ~iommu() override;

protected:
    // the commands this IOMMU has, as their opcode and function, bits 9:0; and IOFENCE.C's AV: write DATA when done
    static constexpr uint64_t command_iotinval_vma = 1;
    static constexpr uint64_t command_iofence_c = 2;
    static constexpr uint64_t command_iodir_inval_ddt = 3;
    static constexpr uint64_t iofence_av = uint64_t(1) << 10;
    // the types of transaction a fault record says it was for: a read or write of an untranslated address
    static constexpr uint64_t ttyp_untranslated_read = 2;
    static constexpr uint64_t ttyp_untranslated_write = 3;

    void reset_cb();
    void translate(tlm::tlm_generic_payload& gp, sc_core::sc_time& delay);
    // runs the commands from the head of the command queue to its tail, each time software moves the tail
    void run_commands();
    // sets the wired interrupt from what is pending and what may interrupt; the one process that writes it
    void update_irq();
    // stops the command queue with error, which software clears, and has it seen to
    template <typename Field> void stop_commands(Field& error, sc_core::sc_time const& delay);
    // runs the command whose doublewords are first and second; false if this IOMMU does not have it
    bool run(uint64_t first, uint64_t second, sc_core::sc_time& delay);
    // writes a fault record for a transaction of type ttyp from a device, if the fault queue is on
    void record(iommu_fault_cause cause, uint64_t ttyp, uint32_t device_id, uint64_t iova, sc_core::sc_time& delay);
    // writes 4 bytes at a physical address through dma_o, least significant first; false if nothing answered
    bool store(uint64_t pa, uint32_t value, sc_core::sc_time& delay);
    // writes length bytes at a physical address through dma_o; false if nothing answered
    bool store(uint64_t pa, uint8_t* data, size_t length, sc_core::sc_time& delay);
    // reads the 8 bytes at a physical address through dma_o, least significant first; false if nothing answered
    bool load(uint64_t pa, uint64_t& value, sc_core::sc_time& delay);

    sc_core::sc_time clk_period;
    sc_core::sc_event commands_written;
    sc_core::sc_event irq_changed;
    std::unique_ptr<iommu_regs> regs;
};

} // namespace rvi
} // namespace vpvper

#endif // _RVI_IOMMU_H_
