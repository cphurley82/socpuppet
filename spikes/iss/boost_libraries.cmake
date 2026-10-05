# The parts of Boost the ISS candidates need beyond what socpuppet itself
# uses. Boost is fetched once, in cmake/Dependencies.cmake, with a list of
# the libraries wanted, so the list has to be known before that runs.
#
# For riscv-vp: format and io. (DBT-RISE-RISCV's are in the main list now.)
set(SOCPUPPET_SPIKE_BOOST_LIBRARIES
  format
  io)
