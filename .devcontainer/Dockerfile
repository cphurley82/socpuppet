# The same environment CI uses: Ubuntu 24.04 with GCC 13.
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        device-tree-compiler \
        gdb \
        git \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# uv supplies Python, cmake and ninja (see pyproject.toml).
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /usr/local/bin/

# Keep the virtual environment out of the mounted workspace so it does not
# collide with a .venv created on the host.
ENV UV_PROJECT_ENVIRONMENT=/opt/socpuppet-venv \
    UV_LINK_MODE=copy
