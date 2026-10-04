# The parts of Boost the ISS candidates need beyond what socpuppet itself
# uses. Boost is fetched once, in cmake/Dependencies.cmake, with a list of
# the libraries wanted, so the list has to be known before that runs.
#
# For DBT-RISE-RISCV: its interpreter is built on coroutines, its GDB server
# on asio, and its debugger command parser on spirit.
# For riscv-vp: format and io.
set(SOCPUPPET_SPIKE_BOOST_LIBRARIES
  asio
  bind
  context
  coroutine
  coroutine2
  foreach
  format
  fusion
  io
  lexical_cast
  optional
  phoenix
  program_options
  serialization
  smart_ptr
  spirit
  thread
  tokenizer
  tuple
  variant)
