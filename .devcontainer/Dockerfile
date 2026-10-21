# The same environment CI uses by default: Ubuntu 26.04 with GCC 15.
FROM ubuntu:26.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        acpica-tools \
        bc \
        bison \
        build-essential \
        ca-certificates \
        curl \
        device-tree-compiler \
        e2fsprogs \
        flex \
        gdb \
        git \
        uuid-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# What tools/build_qbox.py needs to build QBox and its QEMU, for the
# qbox_cpu (docs/setup.md).
RUN apt-get update && apt-get install -y --no-install-recommends \
        bison flex libasio-dev libelf-dev libepoxy-dev libglib2.0-dev \
        libjpeg-turbo8-dev libpixman-1-dev libsdl2-dev libslirp-dev \
        libvirglrenderer-dev libzip-dev lld llvm meson ninja-build \
        ocl-icd-opencl-dev pkg-config python3-dev python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# uv supplies Python, cmake and ninja (see pyproject.toml).
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /usr/local/bin/

# Keep the virtual environment out of the mounted workspace so it does not
# collide with a .venv created on the host.
ENV UV_PROJECT_ENVIRONMENT=/opt/socpuppet-venv \
    UV_LINK_MODE=copy
