/*
 * Copyright (c) 2026 socpuppet contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef _RVI_IOMMU_H_
#define _RVI_IOMMU_H_

#include <cstddef>
#include <cstdint>
#include <memory>
#include <scc/tlm_target.h>
#include <scc/utilities.h>
#include <tlm/scc/initiator_mixin.h>
#include <tlm/scc/target_mixin.h>

namespace vpvper {
namespace rvi {

class iommu_regs;
enum class iommu_fault_cause : uint16_t;

// the type of transaction a fault record says it was for: a read or write of an untranslated address
enum class iommu_transaction_type : uint8_t { untranslated_read = 2, untranslated_write = 3 };

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
    static constexpr uint64_t iofence_av = uint64_t(1) << 10U;
    // how big a command and a fault record are
    static constexpr size_t command_size = 16;
    static constexpr size_t record_size = 32;
    // how big a page is: what a transaction is translated by
    static constexpr uint64_t page_size = 4096;

    void reset_cb();
    void translate(tlm::tlm_generic_payload& gp, sc_core::sc_time& delay);
    // sends length bytes of a transaction, from offset, on through dma_o at a physical address, and gives the
    // transaction their response
    void forward(tlm::tlm_generic_payload& gp, unsigned offset, unsigned length, uint64_t pa, sc_core::sc_time& delay);
    // runs the commands from the head of the command queue to its tail, each time software moves the tail
    void run_commands();
    // sets the wired interrupt from what is pending and what may interrupt; the one process that writes it
    void update_irq();
    // stops the command queue with error, which software clears, and has it seen to
    template <typename Field> void stop_commands(Field& error, sc_core::sc_time const& delay);
    // runs the command whose doublewords are first and second; false if this IOMMU does not have it
    bool run(uint64_t first, uint64_t second, sc_core::sc_time& delay);
    // writes a fault record for a transaction of a type from a device, if the fault queue is on
    void record(iommu_fault_cause cause, iommu_transaction_type type, uint32_t device_id, uint64_t iova, sc_core::sc_time& delay);
    // where entry index of a queue of entries of size bytes, at the page ppn, is
    static uint64_t slot(uint64_t ppn, uint32_t index, size_t size);
    // index as an index into a queue of 2^(log2sz_1 + 1) entries, and the index after it
    static uint32_t wrap(uint32_t index, uint64_t log2sz_1);
    static uint32_t after(uint32_t index, uint64_t log2sz_1);
    // writes the low length bytes of value at bytes, least significant first
    static void to_le(uint8_t* bytes, uint64_t value, size_t length);
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
