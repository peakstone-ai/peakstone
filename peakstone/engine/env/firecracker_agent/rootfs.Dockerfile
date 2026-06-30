# Toolchain rootfs for the Peakstone Firecracker TEST sandbox.
#
# build-image.sh (FC_TOOLCHAIN=1) turns this into an ext4 image: docker build -> docker export ->
# mkfs.ext4 -d. Docker is BUILD-TIME ONLY (the privileged installs happen here); the runtime stays
# KVM-only with no Docker on the host. The ps-agent is injected after export, so this image carries
# no agent — just a /bin/sh and every toolchain the language runners (engine/sandbox.py) invoke.
#
# Pin everything: a versioned toolchain image is the canonical, reproducible test environment, so the
# same lib versions run everywhere and deterministic reproductions (repro_sig) actually match across
# machines. Bump a pin deliberately and re-tag the image; it's content-addressed like the suite.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ARG GO_VERSION=1.23.4
ARG NODE_MAJOR=22
ARG RUST_VERSION=1.83.0
# docker buildx sets TARGETARCH (amd64/arm64); map to the names go/rust downloads use.
ARG TARGETARCH=amd64

# --- base: python3.12 + pytest, native build deps, scm/utils ---------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git xz-utils software-properties-common tzdata \
        python3 python3-venv python3-pip \
        build-essential pkg-config libssl-dev \
    && pip3 install --no-cache-dir --break-system-packages pytest \
    && rm -rf /var/lib/apt/lists/*

# --- node + the TS runner (tsx) + typescript (global) ----------------------------------------
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g tsx typescript \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

# --- go --------------------------------------------------------------------------------------
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${TARGETARCH}.tar.gz" | tar -C /usr/local -xz

# --- rust + cargo (stable, minimal profile) --------------------------------------------------
ENV RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal \
        --default-toolchain "${RUST_VERSION}" \
    && chmod -R a+rX /usr/local/rustup /usr/local/cargo

# --- BigCodeBench env: pinned older stack (pandas<3 / numpy<2), authored for Python 3.10 (no wheels
#     on 3.12), isolated in its own venv. engine config [run.envs].bigcodebench must point here.
#     Mirrors build_bcb_env.sh: pytest + upstream requirements-eval.txt (best-effort per-pkg fallback).
RUN add-apt-repository -y ppa:deadsnakes/ppa && apt-get update \
    && apt-get install -y --no-install-recommends python3.10 python3.10-venv python3.10-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python3.10 -m venv /opt/peakstone/bcb-venv \
    && /opt/peakstone/bcb-venv/bin/pip install --no-cache-dir -U pip wheel setuptools pytest \
    && curl -fsSL https://raw.githubusercontent.com/bigcode-project/bigcodebench/main/Requirements/requirements-eval.txt -o /tmp/bcb.txt \
    && ( /opt/peakstone/bcb-venv/bin/pip install --no-cache-dir --prefer-binary -r /tmp/bcb.txt \
         || while read -r l; do l="${l%%#*}"; l="$(echo "$l" | xargs)"; [ -z "$l" ] && continue; \
              /opt/peakstone/bcb-venv/bin/pip install --no-cache-dir --prefer-binary "$l" || echo "bcb SKIP: $l"; \
            done < /tmp/bcb.txt ) \
    && rm -f /tmp/bcb.txt

# the python runner invokes bare `python` (Ubuntu ships only python3); `time` backs guest peak-RSS.
# Kept as a late layer so the heavy toolchain layers above stay cached on rebuild.
RUN apt-get update && apt-get install -y --no-install-recommends python-is-python3 time \
    && rm -rf /var/lib/apt/lists/*

# --- declare the toolchain environment for the guest agent -----------------------------------
# docker export drops image ENV/PATH, and the agent boots as PID 1 with no PATH. The agent seeds its
# command environment from /etc/environment (see ps-agent loadBaseEnv), so write everything here.
RUN printf '%s\n' \
      'PATH=/usr/local/cargo/bin:/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
      'GOROOT=/usr/local/go' \
      'GOPATH=/root/go' \
      'GOTOOLCHAIN=local' \
      'GOFLAGS=-mod=mod' \
      'RUSTUP_HOME=/usr/local/rustup' \
      'CARGO_HOME=/usr/local/cargo' \
      'HOME=/root' \
      'LANG=C.UTF-8' \
      'TZ=UTC' \
      > /etc/environment

RUN mkdir -p /usr/local/bin /work
WORKDIR /work
