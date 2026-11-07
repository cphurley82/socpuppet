#!/bin/sh
# The packages a Linux wheel's build needs that the manylinux image lacks.
# cibuildwheel runs this once in its container, before the first wheel
# (pyproject.toml's before-all), where no Python of ours is on the PATH yet.
#
# - zlib's headers, for SCC's trace writer. The library itself is part of
#   the manylinux baseline, so the wheel may depend on it.
# - ccache, which lets the second and third wheel reuse what the first
#   compiled: nearly everything in a wheel is SystemC, SCC, Boost and the
#   CPU, which do not care which Python it is for. It comes from EPEL, the
#   extra packages for the image's distribution.
#
# ⚠️ A mirror of the distribution's packages can answer with an empty list
# of what it holds, and dnf gives up on a parse error instead of asking
# another mirror. So a failure is tried again, after `dnf clean all`, which
# makes dnf fetch its list of mirrors and their metadata afresh.

tries=5
try=1
until dnf install -y zlib-devel epel-release && dnf install -y ccache; do
  if [ "$try" -ge "$tries" ]; then
    echo "❌ dnf failed $tries times. A mirror of the distribution's" \
      "packages may be down: build the wheels again later." >&2
    exit 1
  fi
  try=$((try + 1))
  echo "⚠️ dnf failed; cleaning its cache and trying again" \
    "($try of $tries)." >&2
  dnf clean all
  sleep 15
done
