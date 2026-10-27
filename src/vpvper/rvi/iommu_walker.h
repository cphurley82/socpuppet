/*
 * Copyright (c) 2026 socpuppet contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef _RVI_IOMMU_WALKER_H_
#define _RVI_IOMMU_WALKER_H_

#include <cstdint>
#include <functional>
#include <optional>
#include <utility>

namespace vpvper {
namespace rvi {

// why the IOMMU refused a request, as the cause field of a fault record says it. The names are Linux's and QEMU's for
// the specification's causes.
enum class iommu_fault_cause : uint16_t {
    dma_disabled = 256,
    ddt_load_fault = 257,
    ddt_invalid = 258,
    ddt_misconfigured = 259,
    ttyp_blocked = 260,
};

// what ddtp.iommu_mode says the device directory is: nothing gets through, everything gets through as it is, or a
// directory of one, two or three levels of tables
enum class iommu_ddt_mode : uint8_t { off = 0, bare = 1, one_level = 2, two_level = 3, three_level = 4 };

// the device directory as ddtp describes it: its mode, and the physical address of its root table
struct iommu_device_directory {
    iommu_ddt_mode mode;
    uint64_t root;
};

// what a device asks the IOMMU to translate
struct iommu_request {
    uint32_t device_id;
    uint64_t iova;
};

// where a request goes, or why it may not
struct iommu_translation {
    uint64_t pa{0};
    std::optional<iommu_fault_cause> fault;
};

// the tables of the RISC-V IOMMU specification that live in memory, walked to translate a request: the
// device directory, and the page tables a device context points at
class iommu_walker {
public:
    // reads the 8 bytes at a physical address, least significant first; false if nothing answered
    using load_fn = std::function<bool(uint64_t pa, uint64_t& value)>;

    explicit iommu_walker(load_fn fn)
    : load(std::move(fn)) {}

    // translates a request under the device directory ddt
    iommu_translation translate(iommu_device_directory const& ddt, iommu_request const& request) const {
        unsigned levels = 0;
        switch(ddt.mode) {
        case iommu_ddt_mode::off:
            return {0, iommu_fault_cause::dma_disabled};
        case iommu_ddt_mode::bare:
            return {request.iova, {}};
        case iommu_ddt_mode::one_level:
            levels = 1;
            break;
        case iommu_ddt_mode::two_level:
            levels = 2;
            break;
        case iommu_ddt_mode::three_level:
            levels = 3;
            break;
        }
        // a device the directory has no room for
        if(request.device_id >> device_id_bits[levels - 1])
            return {0, iommu_fault_cause::ttyp_blocked};
        uint64_t table = ddt.root;
        for(unsigned level = levels - 1; level > 0; --level) {
            uint64_t ddte = 0;
            if(!load(table + ddi(request.device_id, level) * 8, ddte))
                return {0, iommu_fault_cause::ddt_load_fault};
            if(!(ddte & ddte_v))
                return {0, iommu_fault_cause::ddt_invalid};
            if(ddte & ddte_reserved)
                return {0, iommu_fault_cause::ddt_misconfigured};
            table = page_of(ddte);
        }
        uint64_t context[device_context_words] = {};
        uint64_t const at = table + ddi(request.device_id, 0) * device_context_size;
        for(unsigned word = 0; word < device_context_words; ++word)
            if(!load(at + word * 8, context[word]))
                return {0, iommu_fault_cause::ddt_load_fault};
        uint64_t const tc = context[0], iohgatp = context[1], fsc = context[3];
        if(!(tc & tc_v))
            return {0, iommu_fault_cause::ddt_invalid};
        // V is the only control of a context this walker accepts yet: no ATS, no page requests, no process contexts,
        // and DTF waits for fault records
        if(tc & ~tc_v)
            return {0, iommu_fault_cause::ddt_misconfigured};
        // there is one stage of translation, so no second stage may be asked for
        if(mode_of(iohgatp) != atp_mode_bare)
            return {0, iommu_fault_cause::ddt_misconfigured};
        // and the first stage is Sv39 or nothing
        if(mode_of(fsc) != atp_mode_bare && mode_of(fsc) != atp_mode_sv39)
            return {0, iommu_fault_cause::ddt_misconfigured};
        return {request.iova, {}};
    }

private:
    // a non-leaf entry of the directory's V, and its reserved bits: 9:1 and 63:54
    static constexpr uint64_t ddte_v = 1;
    static constexpr uint64_t ddte_reserved = 0xffc0'0000'0000'03feULL;
    // a device context in the base format: tc, iohgatp, ta and fsc; and tc.V
    static constexpr uint64_t device_context_size = 32;
    static constexpr unsigned device_context_words = 4;
    static constexpr uint64_t tc_v = 1;
    // the MODE field of iohgatp or fsc, bits 63:60, and the modes it may have here
    static uint64_t mode_of(uint64_t atp) { return atp >> 60; }
    static constexpr uint64_t atp_mode_bare = 0;
    static constexpr uint64_t atp_mode_sv39 = 8;

    // how wide a device ID a directory of one, two and three levels indexes
    static constexpr unsigned device_id_bits[] = {7, 16, 24};

    // a device ID's index into the table at a level of the directory, where level 0 is the leaf: with base-format
    // contexts, bits 6:0, 15:7 and 23:16
    static uint64_t ddi(uint32_t device_id, unsigned level) {
        switch(level) {
        case 0:
            return device_id & 0x7f;
        case 1:
            return (device_id >> 7) & 0x1ff;
        default:
            return (device_id >> 16) & 0xff;
        }
    }

    // the page that the PPN field of a directory entry, bits 53:10, names
    static uint64_t page_of(uint64_t ddte) { return ((ddte >> 10) & ((uint64_t(1) << 44) - 1)) << 12; }

    load_fn load;
};

} // namespace rvi
} // namespace vpvper

#endif // _RVI_IOMMU_WALKER_H_
