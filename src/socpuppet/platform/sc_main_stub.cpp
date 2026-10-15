// QBox's SystemC is a shared library, and the main() inside it calls
// sc_main(), which every SystemC program is expected to define. socpuppet
// defines main() itself, or is loaded by Python, so that sc_main() is never
// called. It still has to exist: a program will not link without it, and
// Python loads the extension with every name resolved at once (RTLD_NOW).
// Visible, because the extension hides its names unless told otherwise.
//
// Built only when SystemC is QBox's (cmake/Dependencies.cmake). A static
// SystemC leaves its main() and the call out of the link.

// SystemC declares it this way, in sysc/kernel/sc_externs.h.
// NOLINTNEXTLINE(modernize-avoid-c-arrays)
extern "C" [[gnu::visibility("default")]] int sc_main(int /*argc*/,
                                                      char* /*argv*/[]) {
  return 0;
}
