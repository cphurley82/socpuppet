# Source patches to riscv-vp, applied in its source directory after it is
# fetched. Written as replacements, so that applying them twice is harmless.

# Patch 1: its macro for a named thread is written against the inside of
# SystemC 2.3. This is the SystemC 3.0 form, as its fork riscv-vp-plusplus
# has it.
set(file vp/src/util/common.h)
file(READ ${file} text)
string(REPLACE
  "#define SC_NAMED_THREAD(func, name) declare_thread_process(func##_handle, name, SC_CURRENT_USER_MODULE, func)"
  "#define SC_NAMED_THREAD(func, name) \\\n\tSC_PROCESS_MACRO_BEGIN_ \\\n\tthis->declare_thread_process(SC_MAKE_FUNC_PTR(SC_CURRENT_USER_MODULE_TYPE, func), name) SC_PROCESS_MACRO_END_"
  patched "${text}")
if(NOT patched STREQUAL text)
  file(WRITE ${file} "${patched}")
endif()

# Patch 2: the 32-bit and the 64-bit ISS each define two global tables
# with the same names, so the two cannot be linked into one program. Give
# each file its own copy.
foreach(file vp/src/core/rv32/iss.cpp vp/src/core/rv64/iss.cpp)
  file(READ ${file} text)
  string(REPLACE "\nconst char *regnames[] = {" "\nstatic const char *regnames[] = {"
    patched "${text}")
  string(REPLACE "\nint regcolors[] = {" "\nstatic int regcolors[] = {"
    patched "${patched}")
  if(NOT patched STREQUAL text)
    file(WRITE ${file} "${patched}")
  endif()
endforeach()
