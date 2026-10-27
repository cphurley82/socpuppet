/*
 * Copyright (c) 2026 socpuppet contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Written by hand from iommu.rdl in the shape peakrdl_mnrs generates, which
 * is MINRES's own generator and not available where this was written, less
 * the semicolon after each BEGIN_BF_DECL and BF_FIELD, whose expansions
 * have their own.
 */

#ifndef _IOMMU_REGS_H_
#define _IOMMU_REGS_H_

#include <scc/register.h>
#include <scc/tlm_target.h>
#include <scc/utilities.h>
#include <util/bit_field.h>

namespace vpvper {
namespace rvi {

class iommu_regs : public sc_core::sc_module, public scc::resetable {
public:
    //////////////////////////////////////////////////////////////////////////////
    // storage declarations
    //////////////////////////////////////////////////////////////////////////////
    BEGIN_BF_DECL(capabilities_t, uint64_t)
    BF_FIELD(version, 0, 8)
    BF_FIELD(sv39, 9, 1)
    BF_FIELD(msi_flat, 22, 1)
    BF_FIELD(igs, 28, 2)
    BF_FIELD(pas, 32, 6)
    END_BF_DECL() r_capabilities;

    BEGIN_BF_DECL(fctl_t, uint32_t)
    BF_FIELD(be, 0, 1)
    BF_FIELD(wsi, 1, 1)
    BF_FIELD(gxl, 2, 1)
    END_BF_DECL() r_fctl;

    BEGIN_BF_DECL(ddtp_t, uint64_t)
    BF_FIELD(iommu_mode, 0, 4)
    BF_FIELD(busy, 4, 1)
    BF_FIELD(ppn, 10, 44)
    END_BF_DECL() r_ddtp;

    BEGIN_BF_DECL(cqb_t, uint64_t)
    BF_FIELD(log2sz_1, 0, 5)
    BF_FIELD(ppn, 10, 44)
    END_BF_DECL() r_cqb;

    uint32_t r_cqh;

    uint32_t r_cqt;

    BEGIN_BF_DECL(fqb_t, uint64_t)
    BF_FIELD(log2sz_1, 0, 5)
    BF_FIELD(ppn, 10, 44)
    END_BF_DECL() r_fqb;

    uint32_t r_fqh;

    uint32_t r_fqt;

    BEGIN_BF_DECL(cqcsr_t, uint32_t)
    BF_FIELD(cqen, 0, 1)
    BF_FIELD(cie, 1, 1)
    BF_FIELD(cqmf, 8, 1)
    BF_FIELD(cmd_to, 9, 1)
    BF_FIELD(cmd_ill, 10, 1)
    BF_FIELD(fence_w_ip, 11, 1)
    BF_FIELD(cqon, 16, 1)
    BF_FIELD(busy, 17, 1)
    END_BF_DECL() r_cqcsr;

    BEGIN_BF_DECL(fqcsr_t, uint32_t)
    BF_FIELD(fqen, 0, 1)
    BF_FIELD(fie, 1, 1)
    BF_FIELD(fqmf, 8, 1)
    BF_FIELD(fqof, 9, 1)
    BF_FIELD(fqon, 16, 1)
    BF_FIELD(busy, 17, 1)
    END_BF_DECL() r_fqcsr;

    BEGIN_BF_DECL(ipsr_t, uint32_t)
    BF_FIELD(cip, 0, 1)
    BF_FIELD(fip, 1, 1)
    BF_FIELD(pmip, 2, 1)
    BF_FIELD(pip, 3, 1)
    END_BF_DECL() r_ipsr;

    BEGIN_BF_DECL(icvec_t, uint64_t)
    BF_FIELD(civ, 0, 4)
    BF_FIELD(fiv, 4, 4)
    BF_FIELD(pmiv, 8, 4)
    BF_FIELD(piv, 12, 4)
    END_BF_DECL() r_icvec;

    //////////////////////////////////////////////////////////////////////////////
    // register declarations
    //////////////////////////////////////////////////////////////////////////////
    scc::sc_register<capabilities_t> capabilities;
    scc::sc_register<fctl_t> fctl;
    scc::sc_register<ddtp_t> ddtp;
    scc::sc_register<cqb_t> cqb;
    scc::sc_register<uint32_t> cqh;
    scc::sc_register<uint32_t> cqt;
    scc::sc_register<fqb_t> fqb;
    scc::sc_register<uint32_t> fqh;
    scc::sc_register<uint32_t> fqt;
    scc::sc_register<cqcsr_t> cqcsr;
    scc::sc_register<fqcsr_t> fqcsr;
    scc::sc_register<ipsr_t> ipsr;
    scc::sc_register<icvec_t> icvec;

    iommu_regs(sc_core::sc_module_name nm);

    template <unsigned BUSWIDTH = 32> void registerResources(scc::tlm_target<BUSWIDTH>& target);
};

//////////////////////////////////////////////////////////////////////////////
// member functions
//////////////////////////////////////////////////////////////////////////////

inline iommu_regs::iommu_regs(sc_core::sc_module_name nm)
: sc_core::sc_module(nm)
, NAMED(capabilities, r_capabilities, 0x3810000210UL, *this)
, NAMED(fctl, r_fctl, 0x2, *this)
, NAMED(ddtp, r_ddtp, 0, *this)
, NAMED(cqb, r_cqb, 0, *this)
, NAMED(cqh, r_cqh, 0, *this)
, NAMED(cqt, r_cqt, 0, *this)
, NAMED(fqb, r_fqb, 0, *this)
, NAMED(fqh, r_fqh, 0, *this)
, NAMED(fqt, r_fqt, 0, *this)
, NAMED(cqcsr, r_cqcsr, 0, *this)
, NAMED(fqcsr, r_fqcsr, 0, *this)
, NAMED(ipsr, r_ipsr, 0, *this)
, NAMED(icvec, r_icvec, 0, *this) {}

template <unsigned BUSWIDTH> inline void iommu_regs::registerResources(scc::tlm_target<BUSWIDTH>& target) {
    target.addResource(capabilities, 0x0UL);
    target.addResource(fctl, 0x8UL);
    target.addResource(ddtp, 0x10UL);
    target.addResource(cqb, 0x18UL);
    target.addResource(cqh, 0x20UL);
    target.addResource(cqt, 0x24UL);
    target.addResource(fqb, 0x28UL);
    target.addResource(fqh, 0x30UL);
    target.addResource(fqt, 0x34UL);
    target.addResource(cqcsr, 0x48UL);
    target.addResource(fqcsr, 0x4cUL);
    target.addResource(ipsr, 0x54UL);
    target.addResource(icvec, 0x2f8UL);
}
} // namespace rvi
} // namespace vpvper

#endif // _IOMMU_REGS_H_
