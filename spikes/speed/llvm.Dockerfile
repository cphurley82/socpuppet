# The devcontainer's image with LLVM 19's development package, for the
# speed spike's LLVM columns in Docker (docker.sh --llvm). DBT-RISE is
# written against LLVM 19.
ARG BASE=socpuppet-dev:amd64
FROM ${BASE}
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        llvm-19-dev libzstd-dev libedit-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*
