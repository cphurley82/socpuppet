# The environment the NPU spike builds QBox's Hexagon in: the ISS spike's
# image (spikes/iss/qbox/Dockerfile) plus clang, which is what compiles C
# for a Hexagon core. Ubuntu's LLVM is built with every target in it,
# Hexagon included, so no toolchain of Qualcomm's is needed for a
# bare-metal program. QBox and QEMU are not in the image; build.sh fetches
# and builds them into a volume.
FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bison ca-certificates clang cmake flex g++ gcc git libasio-dev \
        libelf-dev libepoxy-dev libglib2.0-dev libjpeg-turbo8-dev \
        libpixman-1-dev libsdl2-dev libslirp-dev libvirglrenderer-dev \
        libzip-dev lld llvm make meson ninja-build ocl-icd-opencl-dev \
        pkg-config python3 python3-dev python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*
