#ifndef CMAKE_SHIMS_SPDK_STDINC_H_
#define CMAKE_SHIMS_SPDK_STDINC_H_

// Stands in for SPDK's "spdk/stdinc.h", which includes most of POSIX and a
// good deal of Linux. SPDK's NVMe definitions (spdk/nvme_spec.h) are the one
// SPDK header socpuppet borrows, and they need only these.

#include <assert.h>   // NOLINT(modernize-deprecated-headers): shared with C
#include <stdbool.h>  // NOLINT(modernize-deprecated-headers)
#include <stddef.h>   // NOLINT(modernize-deprecated-headers)
#include <stdint.h>   // NOLINT(modernize-deprecated-headers)

#endif  // CMAKE_SHIMS_SPDK_STDINC_H_
