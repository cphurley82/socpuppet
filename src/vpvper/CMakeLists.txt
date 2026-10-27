# Models written for VPV-Peripherals, MINRES's library of peripheral models,
# to be offered upstream (docs/upstream.md). The tree under here is laid out
# as VPV's is, so a file here has the same path there, and is included the
# same way: <rvi/iommu_walker.h>, as VPV's own <rvi/aplic.h> is.
add_library(socpuppet_vpvper INTERFACE)
target_sources(socpuppet_vpvper INTERFACE
  FILE_SET HEADERS BASE_DIRS ${CMAKE_CURRENT_SOURCE_DIR} FILES
    rvi/iommu_walker.h)
socpuppet_check_headers(socpuppet_vpvper)
