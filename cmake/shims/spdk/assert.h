#ifndef CMAKE_SHIMS_SPDK_ASSERT_H_
#define CMAKE_SHIMS_SPDK_ASSERT_H_

// Stands in for SPDK's "spdk/assert.h". SPDK's NVMe definitions check the
// size of every structure against the specification with this macro.
//
// SPDK's own header defines it as a static assertion only `#ifdef
// static_assert`. That is true in C, where static_assert is a macro, and
// false in C++, where it is a keyword, so in C++ every check would quietly
// turn into nothing. This one keeps them (see docs/upstream.md).

#define SPDK_STATIC_ASSERT(cond, msg) static_assert(cond, msg)

#endif  // CMAKE_SHIMS_SPDK_ASSERT_H_
