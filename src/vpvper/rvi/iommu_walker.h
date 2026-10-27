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
    read_access_fault = 5,
    write_access_fault = 7,
    read_page_fault = 13,
    write_page_fault = 15,
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
    bool is_write;
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
            if(!load(at + uint64_t(word) * 8, context[word]))
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
        switch(mode_of(fsc)) {
        case atp_mode_bare:
            return {request.iova, {}};
        case atp_mode_sv39:
            return translate_sv39(atp_root(fsc), request);
        default:
            return {0, iommu_fault_cause::ddt_misconfigured};
        }
    }

private:
    // the first stage: Sv39's three levels of page tables from the table at root
    iommu_translation translate_sv39(uint64_t root, iommu_request const& request) const {
        // Sv39 maps 39 bits, and bits 63:39 copy bit 38
        uint64_t const top = request.iova >> 38;
        if(top != 0 && top != (~uint64_t(0) >> 38))
            return {0, page_fault(request)};
        uint64_t table = root;
        for(unsigned level = sv39_levels; level-- > 0;) {
            uint64_t pte = 0;
            if(!load(table + vpn(request.iova, level) * 8, pte))
                return {0, access_fault(request)};
            // not valid, W without R, or bits 63:54, all of which Sv39 reserves without extensions this IOMMU lacks
            if(!(pte & pte_v) || (pte & (pte_r | pte_w)) == pte_w || (pte & pte_reserved))
                return {0, page_fault(request)};
            // a leaf: a page of 4 KiB at level 0, or of 2 MiB or 1 GiB above it
            if(pte & (pte_r | pte_w | pte_x)) {
                // a superpage starts on a boundary of its own size
                if(page_of(pte) & page_offset_mask(level))
                    return {0, page_fault(request)};
                if(!(pte & (request.is_write ? pte_w : pte_r)))
                    return {0, page_fault(request)};
                // a request with no process ID is a user-mode access
                if(!(pte & pte_u))
                    return {0, page_fault(request)};
                // the IOMMU does not set A or D itself, so the driver must have
                if(!(pte & pte_a) || (request.is_write && !(pte & pte_d)))
                    return {0, page_fault(request)};
                return {page_of(pte) | (request.iova & page_offset_mask(level)), {}};
            }
            table = page_of(pte);
        }
        // the last level pointed at another table
        return {0, page_fault(request)};
    }

    // the page fault a request is refused with
    static iommu_fault_cause page_fault(iommu_request const& request) {
        return request.is_write ? iommu_fault_cause::write_page_fault : iommu_fault_cause::read_page_fault;
    }

    // the access fault a request is refused with when a page-table entry cannot be read
    static iommu_fault_cause access_fault(iommu_request const& request) {
        return request.is_write ? iommu_fault_cause::write_access_fault : iommu_fault_cause::read_access_fault;
    }

    // Sv39's levels; an address's index into the table at a level, where level 0 is the last; and the bits of an
    // address that are its offset into a page mapped at a level
    static constexpr unsigned sv39_levels = 3;
    static uint64_t vpn(uint64_t iova, unsigned level) { return (iova >> (12 + 9 * level)) & 0x1ff; }
    static uint64_t page_offset_mask(unsigned level) { return (uint64_t(1) << (12 + 9 * level)) - 1; }
    // a page-table entry's V, what it allows (R, W, X, U), A and D, and bits 63:54, which Sv39 reserves without
    // extensions
    static constexpr uint64_t pte_v = 1 << 0;
    static constexpr uint64_t pte_r = 1 << 1;
    static constexpr uint64_t pte_w = 1 << 2;
    static constexpr uint64_t pte_x = 1 << 3;
    static constexpr uint64_t pte_u = 1 << 4;
    static constexpr uint64_t pte_a = 1 << 6;
    static constexpr uint64_t pte_d = 1 << 7;
    static constexpr uint64_t pte_reserved = 0xffc0'0000'0000'0000ULL;

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
    // the root table that the PPN field of iohgatp or fsc, bits 43:0, names
    static uint64_t atp_root(uint64_t atp) { return (atp & ((uint64_t(1) << 44) - 1)) << 12; }

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

    // the page that the PPN field of a directory entry or a page-table entry, bits 53:10, names
    static uint64_t page_of(uint64_t entry) { return ((entry >> 10) & ((uint64_t(1) << 44) - 1)) << 12; }

    load_fn load;
};

} // namespace rvi
} // namespace vpvper

#endif // _RVI_IOMMU_WALKER_H_
