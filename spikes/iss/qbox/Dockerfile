# The environment the ISS spike builds QBox in: Ubuntu 24.04 with the
# packages QBox's own scripts/install_dependencies.sh asks for, plus what
# building QEMU needs. QBox and QEMU are not in the image; build.sh fetches
# and builds them into a volume.
FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bison ca-certificates cmake flex g++ gcc git libasio-dev libelf-dev \
        libepoxy-dev libglib2.0-dev libjpeg-turbo8-dev libpixman-1-dev \
        libsdl2-dev libslirp-dev libvirglrenderer-dev libzip-dev lld llvm \
        make meson ninja-build ocl-icd-opencl-dev pkg-config python3 \
        python3-dev python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*
