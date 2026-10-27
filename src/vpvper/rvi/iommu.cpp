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
            // a field is converted to a number on its way: a field assigned a field of its own kind takes the whole
            // word with it
            regs->r_ddtp.iommu_mode = static_cast<uint64_t>(written.iommu_mode);
            regs->r_ddtp.ppn = static_cast<uint64_t>(written.ppn);
        }
        return true;
    });
    // the command queue is on while it is enabled; software clears the errors it reports by writing them
    regs->cqcsr.set_write_cb([this](scc::sc_register<uint32_t>&, uint32_t const& data, sc_core::sc_time&) -> bool {
        iommu_regs::cqcsr_t const written{data};
        regs->r_cqcsr.cqen = static_cast<uint32_t>(written.cqen);
        regs->r_cqcsr.cie = static_cast<uint32_t>(written.cie);
        regs->r_cqcsr.cqon = static_cast<uint32_t>(written.cqen);
        if(written.cmd_ill)
            regs->r_cqcsr.cmd_ill = 0;
        if(written.cqmf)
            regs->r_cqcsr.cqmf = 0;
        // the queue may go on from where it stopped, and its interrupt may now be enabled
        commands_written.notify(sc_core::SC_ZERO_TIME);
        irq_changed.notify(sc_core::SC_ZERO_TIME);
        return true;
    });
    // the head is the IOMMU's to move
    regs->cqh.set_write_cb([](scc::sc_register<uint32_t>&, uint32_t const&, sc_core::sc_time&) { return true; });
    // software puts commands in the queue and then moves the tail past them, which sets the IOMMU running them
    regs->cqt.set_write_cb([this](scc::sc_register<uint32_t>& reg, uint32_t const& data, sc_core::sc_time&) -> bool {
        reg.put(data);
        commands_written.notify(sc_core::SC_ZERO_TIME);
        return true;
    });
    // the fault queue is on while it is enabled; software clears the errors it reports by writing them
    regs->fqcsr.set_write_cb([this](scc::sc_register<uint32_t>&, uint32_t const& data, sc_core::sc_time&) -> bool {
        iommu_regs::fqcsr_t const written{data};
        regs->r_fqcsr.fqen = static_cast<uint32_t>(written.fqen);
        regs->r_fqcsr.fie = static_cast<uint32_t>(written.fie);
        regs->r_fqcsr.fqon = static_cast<uint32_t>(written.fqen);
        if(written.fqmf)
            regs->r_fqcsr.fqmf = 0;
        if(written.fqof)
            regs->r_fqcsr.fqof = 0;
        irq_changed.notify(sc_core::SC_ZERO_TIME);
        return true;
    });
    // software clears what it has seen to by writing it
    regs->ipsr.set_write_cb([this](scc::sc_register<uint32_t>&, uint32_t const& data, sc_core::sc_time&) -> bool {
        regs->r_ipsr = regs->r_ipsr() & ~data;
        irq_changed.notify(sc_core::SC_ZERO_TIME);
        return true;
    });
    // there is one line, so every cause is on vector 0 and stays there
    regs->icvec.set_write_cb([](scc::sc_register<uint64_t>&, uint64_t const&, sc_core::sc_time&) { return true; });
    SC_METHOD(update_irq);
    sensitive << irq_changed;
    // the tail is the IOMMU's to move
    regs->fqt.set_write_cb([](scc::sc_register<uint32_t>&, uint32_t const&, sc_core::sc_time&) { return true; });
    SC_THREAD(run_commands);
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
        record(*translation.fault, gp.is_write() ? ttyp_untranslated_write : ttyp_untranslated_read, device->id, gp.get_address(), delay);
        gp.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
        return;
    }
    auto const iova = gp.get_address();
    gp.set_address(translation.pa);
    dma_o->b_transport(gp, delay);
    gp.set_address(iova);
}

void iommu::run_commands() {
    for(;;) {
        wait(commands_written);
        auto const last = (uint32_t(2) << regs->r_cqb.log2sz_1) - 1;
        while(regs->r_cqcsr.cqon && !regs->r_cqcsr.cmd_ill && !regs->r_cqcsr.cqmf && regs->r_cqh != regs->r_cqt) {
            // a command is 16 bytes, two doublewords
            sc_core::sc_time delay;
            uint64_t const at = (uint64_t(regs->r_cqb.ppn) << 12) + uint64_t(regs->r_cqh) * 16;
            uint64_t first = 0, second = 0;
            // a command that cannot be read, or one this IOMMU does not have, stops the queue at it
            if(!load(at, first, delay) || !load(at + 8, second, delay)) {
                stop_commands(regs->r_cqcsr.cqmf, delay);
                break;
            }
            if(!run(first, second, delay)) {
                stop_commands(regs->r_cqcsr.cmd_ill, delay);
                break;
            }
            regs->r_cqh = (regs->r_cqh + 1) & last;
            wait(delay);
        }
    }
}

template <typename Field> void iommu::stop_commands(Field& error, sc_core::sc_time const& delay) {
    error = 1;
    regs->r_ipsr.cip = 1;
    irq_changed.notify(delay);
    wait(delay);
}

bool iommu::run(uint64_t first, uint64_t second, sc_core::sc_time& delay) {
    // the opcode is bits 6:0 of the first doubleword and the function bits 9:7. Nothing is cached, so IOTINVAL.VMA and
    // IODIR.INVAL_DDT have nothing to do, and a fence has nothing to wait for; with AV, IOFENCE.C writes its DATA, bits
    // 63:32, to the address the second doubleword holds, shifted right by two. The rest are for what this IOMMU does
    // not have: a second stage, process contexts and ATS
    switch(first & 0x3ff) {
    case command_iotinval_vma:
    case command_iodir_inval_ddt:
        return true;
    case command_iofence_c:
        if(first & iofence_av)
            store(second << 2, static_cast<uint32_t>(first >> 32), delay);
        return true;
    default:
        return false;
    }
}

void iommu::record(iommu_fault_cause cause, uint64_t ttyp, uint32_t device_id, uint64_t iova, sc_core::sc_time& delay) {
    if(!regs->r_fqcsr.fqon)
        return;
    // a record is 32 bytes: its header, with the cause in bits 11:0, the type of the transaction in bits 39:34 and
    // the device in bits 63:40; a doubleword kept for later; the address the transaction was for; and a second address
    // that only a second stage has
    std::array<uint64_t, 4> const words{static_cast<uint64_t>(cause) | ttyp << 34 | uint64_t(device_id) << 40, 0, iova, 0};
    std::array<uint8_t, 32> data{};
    for(size_t i = 0; i < data.size(); ++i)
        data[i] = static_cast<uint8_t>(words[i / 8] >> (8 * (i % 8)));
    // the queue is full when one more record would bring the tail to the head, and the record is then lost
    auto const next = (regs->r_fqt + 1) & ((uint32_t(2) << regs->r_fqb.log2sz_1) - 1);
    if(next == regs->r_fqh) {
        regs->r_fqcsr.fqof = 1;
    } else {
        uint64_t const at = (uint64_t(regs->r_fqb.ppn) << 12) + uint64_t(regs->r_fqt) * data.size();
        if(store(at, data.data(), data.size(), delay))
            regs->r_fqt = next;
        else
            regs->r_fqcsr.fqmf = 1;
    }
    regs->r_ipsr.fip = 1;
    irq_changed.notify(sc_core::SC_ZERO_TIME);
}

void iommu::update_irq() {
    // there is one line, so every cause's vector is it: up while a queue that may interrupt is pending
    irq_o.write((regs->r_ipsr.fip && regs->r_fqcsr.fie) || (regs->r_ipsr.cip && regs->r_cqcsr.cie));
}

bool iommu::store(uint64_t pa, uint32_t value, sc_core::sc_time& delay) {
    std::array<uint8_t, 4> data{};
    for(size_t i = 0; i < data.size(); ++i)
        data[i] = static_cast<uint8_t>(value >> (8 * i));
    return store(pa, data.data(), data.size(), delay);
}

bool iommu::store(uint64_t pa, uint8_t* data, size_t length, sc_core::sc_time& delay) {
    tlm::tlm_generic_payload gp;
    gp.set_command(tlm::TLM_WRITE_COMMAND);
    gp.set_address(pa);
    gp.set_data_ptr(data);
    gp.set_data_length(static_cast<unsigned>(length));
    gp.set_streaming_width(static_cast<unsigned>(length));
    dma_o->b_transport(gp, delay);
    return gp.is_response_ok();
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
