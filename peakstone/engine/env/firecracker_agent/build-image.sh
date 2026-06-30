#!/usr/bin/env bash
# Build the Firecracker artifacts for the microvm provider into PEAKSTONE_FC_HOME (default
# ~/.peakstone/fc): the firecracker binary, a guest kernel, the guest agent, and a writable ext4
# rootfs with the agent baked in as /usr/local/bin/ps-agent. No sudo required — the rootfs is built
# with `mkfs.ext4 -d` (populate-from-directory), not a loop mount.
#
# Two rootfs flavours:
#   default (FC_TOOLCHAIN=0): a bare Ubuntu squashfs + agent — vsock exec only (agentic env / Milestone 1).
#   FC_TOOLCHAIN=1: a TEST-sandbox rootfs with the full language toolchain (python/pytest+bcb, node/tsx,
#       go, rust, build-essential), built from rootfs.Dockerfile via `docker build | docker export`.
#       Docker is BUILD-TIME ONLY; the runtime stays KVM-only (no Docker on the host). ~5 GB, ~20 min.
#
# Needs: curl, go, mkfs.ext4 (e2fsprogs >= 1.43); + unsquashfs (default flavour) OR docker (FC_TOOLCHAIN=1).
set -euo pipefail

FC_HOME="${PEAKSTONE_FC_HOME:-$HOME/.peakstone/fc}"
FC_VERSION="${FC_VERSION:-v1.16.0}"
CI="${FC_CI:-v1.15}"            # firecracker-ci kernel/rootfs channel
KERNEL="${FC_KERNEL_VER:-6.1.155}"
FC_TOOLCHAIN="${FC_TOOLCHAIN:-0}"
# the toolchain image needs far more room than the bare agent rootfs
ROOTFS_MB="${FC_ROOTFS_MB:-$([ "$FC_TOOLCHAIN" = 1 ] && echo 8192 || echo 1024)}"
S3="http://spec.ccfc.min.s3.amazonaws.com/firecracker-ci/${CI}/x86_64"
HERE="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$FC_HOME"; cd "$FC_HOME"

echo "==> firecracker ${FC_VERSION}"
if [ ! -x "$FC_HOME/firecracker" ]; then
  curl -sL "https://github.com/firecracker-microvm/firecracker/releases/download/${FC_VERSION}/firecracker-${FC_VERSION}-x86_64.tgz" -o fc.tgz
  tar -xzf fc.tgz
  cp "release-${FC_VERSION}-x86_64/firecracker-${FC_VERSION}-x86_64" firecracker && chmod +x firecracker
  rm -rf fc.tgz "release-${FC_VERSION}-x86_64"
fi
"$FC_HOME/firecracker" --version | head -1

echo "==> guest kernel vmlinux-${KERNEL}"
[ -f vmlinux ] || curl -sL "${S3}/vmlinux-${KERNEL}" -o vmlinux

echo "==> build guest agent (static)"
( cd "$HERE" && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o "$FC_HOME/ps-agent" . )

if [ "$FC_TOOLCHAIN" = 1 ]; then
  echo "==> toolchain rootfs via Docker (python/pytest+bcb, node/tsx, go, rust) — ~${ROOTFS_MB}M"
  command -v docker >/dev/null || { echo "docker is required to build the toolchain rootfs (build-time only)"; exit 1; }
  docker build -t peakstone-fc-rootfs -f "$HERE/rootfs.Dockerfile" "$HERE"
  cid="$(docker create peakstone-fc-rootfs)"
  rm -rf rootdir && mkdir rootdir
  docker export "$cid" | tar -x -C rootdir          # flatten the image fs (export drops ENV; agent reads /etc/environment)
  docker rm "$cid" >/dev/null
else
  echo "==> rootfs (download squashfs, inject agent, build ext4)"
  [ -f ubuntu.squashfs ] || curl -sL "${S3}/ubuntu-24.04.squashfs" -o ubuntu.squashfs
  rm -rf rootdir
  unsquashfs -d rootdir -no-progress ubuntu.squashfs >/dev/null
fi
mkdir -p rootdir/usr/local/bin rootdir/work
cp ps-agent rootdir/usr/local/bin/ps-agent && chmod +x rootdir/usr/local/bin/ps-agent
rm -f rootfs.ext4
mkfs.ext4 -q -F -L rootfs -d rootdir rootfs.ext4 "${ROOTFS_MB}M"
rm -rf rootdir

echo "==> done. artifacts in $FC_HOME:"
ls -1 "$FC_HOME" | grep -E 'firecracker$|vmlinux|rootfs.ext4|ps-agent'
echo "verify: python -m pytest engine/env/tests/test_firecracker.py -q"
