# Source patches to DBT-RISE-Core, applied in its source directory after it
# is fetched. Written as replacements, so that applying them twice is
# harmless.

function(replace_in file before after)
  file(READ ${file} text)
  string(REPLACE "${before}" "${after}" patched "${text}")
  if(NOT patched STREQUAL text)
    file(WRITE ${file} "${patched}")
  endif()
endfunction()

# Patch 1: Boost 1.87 removed asio's old names. `io_service` is now
# `io_context`, and `io_context::work` is now an `executor_work_guard`.
replace_in(src/iss/debugger/serialized_connection.h
  "connection(boost::asio::io_service& io_service)"
  "connection(boost::asio::io_context& io_service)")
replace_in(src/iss/debugger/server.h
  "work_ctrl = new boost::asio::io_context::work(io_service);"
  "work_ctrl = new work_guard(io_service.get_executor());")
replace_in(src/iss/debugger/server.h
  "    boost::asio::io_service::work* work_ctrl;"
  "    using work_guard = boost::asio::executor_work_guard<boost::asio::io_context::executor_type>;\n    work_guard* work_ctrl;")

# Patch 2: the 128-bit integer traits are specialized by reaching into
# GCC's standard library (std::__make_unsigned_selector). Clang's library
# has no such thing, forbids specializing these traits, and already knows
# the 128-bit types. So keep the block for GCC's library only.
replace_in(src/iss/interp/vm_base.h
  "using uint128_t = unsigned __int128;\nnamespace std {"
  "using uint128_t = unsigned __int128;\n#ifdef __GLIBCXX__\nnamespace std {")
replace_in(src/iss/interp/vm_base.h
  "template <> struct is_unsigned<uint128_t> { static constexpr bool value = true; };\n} // namespace std\n#endif"
  "template <> struct is_unsigned<uint128_t> { static constexpr bool value = true; };\n} // namespace std\n#endif // __GLIBCXX__\n#endif")
