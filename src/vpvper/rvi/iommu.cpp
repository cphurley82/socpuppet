/*
 * Copyright (c) 2026 socpuppet contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "iommu.h"
#include "gen/iommu_regs.h"
#include "iommu_walker.h"

#include <array>
#include <scc/utilities.h>

namespace vpvper {
namespace rvi {

iommu::iommu(sc_core::sc_module_name nm)
: sc_core::sc_module(nm)
, tlm_target<>(clk_period)
, NAMEDD(regs, iommu_regs) {
    regs->registerResources(*this);
    // what this IOMMU is, which its reset value says (iommu.rdl), and nothing writes
    regs->capabilities.set_write_cb([](scc::sc_register<uint64_t>&, uint64_t const&, sc_core::sc_time&) { return true; });
    // the modes are Off, Bare and directories of one to three levels; the specification reserves the rest, and a
    // write of one leaves ddtp as it was
    regs->ddtp.set_write_cb([this](scc::sc_register<uint64_t>&, uint64_t const& data, sc_core::sc_time&) -> bool {
        iommu_regs::ddtp_t const written{data};
        if(written.iommu_mode <= static_cast<uint64_t>(iommu_ddt_mode::three_level)) {
            regs->r_ddtp.iommu_mode = written.iommu_mode;
            regs->r_ddtp.ppn = written.ppn;
        }
        return true;
    });
    dma_i.register_b_transport([this](tlm::tlm_generic_payload& gp, sc_core::sc_time& delay) { translate(gp, delay); });
    SC_METHOD(reset_cb);
    sensitive << rst_i;
}

iommu::~iommu() = default;

void iommu::translate(tlm::tlm_generic_payload& gp, sc_core::sc_time& delay) {
    // a transaction that does not say which device it is from cannot be looked up
    iommu_device_id* device = nullptr;
    gp.get_extension(device);
    if(!device) {
        gp.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
        return;
    }
    // the walk reads the tables in memory through dma_o, as late as the transaction it is for
    iommu_walker const walker{[this, &delay](uint64_t pa, uint64_t& value) { return load(pa, value, delay); }};
    uint64_t const mode = regs->r_ddtp.iommu_mode, ppn = regs->r_ddtp.ppn;
    iommu_device_directory const ddt{static_cast<iommu_ddt_mode>(mode), ppn << 12};
    auto const translation = walker.translate(ddt, {device->id, gp.get_address(), gp.is_write()});
    if(translation.fault) {
        gp.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
        return;
    }
    auto const iova = gp.get_address();
    gp.set_address(translation.pa);
    dma_o->b_transport(gp, delay);
    gp.set_address(iova);
}

bool iommu::load(uint64_t pa, uint64_t& value, sc_core::sc_time& delay) {
    std::array<uint8_t, 8> data{};
    tlm::tlm_generic_payload gp;
    gp.set_command(tlm::TLM_READ_COMMAND);
    gp.set_address(pa);
    gp.set_data_ptr(data.data());
    gp.set_data_length(data.size());
    gp.set_streaming_width(data.size());
    dma_o->b_transport(gp, delay);
    if(!gp.is_response_ok())
        return false;
    value = 0;
    for(size_t i = data.size(); i-- > 0;)
        value = (value << 8) | data[i];
    return true;
}

void iommu::reset_cb() {
    if(rst_i.read())
        regs->reset_start();
    else
        regs->reset_stop();
}

} // namespace rvi
} // namespace vpvper
