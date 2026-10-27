/*
 * Copyright (c) 2026 socpuppet contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef _RVI_IOMMU_H_
#define _RVI_IOMMU_H_

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
// three levels and a first stage of Sv39. Not built yet: the command and fault queues, and wired interrupts
class iommu : public sc_core::sc_module, public scc::tlm_target<> {
public:
    sc_core::sc_in<bool> rst_i{"rst_i"};
    // what devices send, to be translated: each transaction says which device sent it with an iommu_device_id
    tlm::scc::target_mixin<tlm::tlm_target_socket<scc::LT>> dma_i{"dma_i"};
    // what was translated, and the IOMMU's own reads and writes of memory
    tlm::scc::initiator_mixin<tlm::tlm_initiator_socket<scc::LT>> dma_o{"dma_o"};

    iommu(sc_core::sc_module_name nm);
    ~iommu() override;

protected:
    void reset_cb();
    void translate(tlm::tlm_generic_payload& gp, sc_core::sc_time& delay);
    // reads the 8 bytes at a physical address through dma_o, least significant first; false if nothing answered
    bool load(uint64_t pa, uint64_t& value, sc_core::sc_time& delay);

    sc_core::sc_time clk_period;
    std::unique_ptr<iommu_regs> regs;
};

} // namespace rvi
} // namespace vpvper

#endif // _RVI_IOMMU_H_
