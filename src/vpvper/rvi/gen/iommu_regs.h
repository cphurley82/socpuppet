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

    BEGIN_BF_DECL(ddtp_t, uint64_t)
    BF_FIELD(iommu_mode, 0, 4)
    BF_FIELD(busy, 4, 1)
    BF_FIELD(ppn, 10, 44)
    END_BF_DECL() r_ddtp;

    //////////////////////////////////////////////////////////////////////////////
    // register declarations
    //////////////////////////////////////////////////////////////////////////////
    scc::sc_register<capabilities_t> capabilities;
    scc::sc_register<ddtp_t> ddtp;

    iommu_regs(sc_core::sc_module_name nm);

    template <unsigned BUSWIDTH = 32> void registerResources(scc::tlm_target<BUSWIDTH>& target);
};

//////////////////////////////////////////////////////////////////////////////
// member functions
//////////////////////////////////////////////////////////////////////////////

inline iommu_regs::iommu_regs(sc_core::sc_module_name nm)
: sc_core::sc_module(nm)
, NAMED(capabilities, r_capabilities, 0x3810000210UL, *this)
, NAMED(ddtp, r_ddtp, 0, *this) {}

template <unsigned BUSWIDTH> inline void iommu_regs::registerResources(scc::tlm_target<BUSWIDTH>& target) {
    target.addResource(capabilities, 0x0UL);
    target.addResource(ddtp, 0x10UL);
}
} // namespace rvi
} // namespace vpvper

#endif // _IOMMU_REGS_H_
