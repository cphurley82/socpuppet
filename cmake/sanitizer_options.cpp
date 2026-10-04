// Built into every program that is compiled with SOCPUPPET_SANITIZE (see
// DevChecks.cmake). The sanitizers call these functions to ask a program
// for its default options, so the options hold however the program is
// started: by ctest, by hand, or by CMake listing its tests.

extern "C" {

// NOLINTNEXTLINE(bugprone-reserved-identifier): the sanitizer's name for it.
const char* __asan_default_options() {
  // The standard library tells AddressSanitizer which part of a vector's
  // memory is in use. Our dependencies are not built with sanitizers, so a
  // vector they have touched looks overrun when it is not.
  return "detect_container_overflow=0";
}

// NOLINTNEXTLINE(bugprone-reserved-identifier): the sanitizer's name for it.
const char* __ubsan_default_options() {
  // Say where the undefined behavior was reached from.
  return "print_stacktrace=1";
}

}  // extern "C"
