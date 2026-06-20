"""Firecracker microVM EnvironmentProvider (PLAN.md §9 P3) — SCAFFOLD.

Why a microVM tier at all: docker already gives real DNS/firewall/NAT/egress control (see docker.py),
so the microVM's headline win is **isolation**, not network realism — a real kernel boundary for the
untrusted, model-generated agent code, plus kernel-level fidelity (own netfilter, raw sockets,
sysctls) that containers restrict. Same EnvSpec / Node interface as the other providers.

STATUS: interface-complete scaffold. `available()` rigorously detects the host prerequisites and
returns False unless they're all present; `provision()` refuses (UnsupportedHost) with the exact
missing pieces rather than half-booting. The VM-config assembly (`vm_config`) is real and unit-tested.
The boot + exec path is documented below and is the remaining work — it needs a host this sandbox
can't provide (KVM access + CAP_NET_ADMIN for TAP), so it is intentionally not faked here.

Intended architecture (for a KVM-capable host):
  * One microVM per node. Boot via the Firecracker API socket: PUT /boot-source (vmlinux + kernel
    args), /drives (an ext4 rootfs, ideally a read-only base + a per-node overlay), /machine-config
    (vcpu/mem), then PUT /actions InstanceStart. The jailer wraps each VM for defense-in-depth.
  * Exec model = a tiny **guest agent over vsock** (Firecracker /vsock). The host speaks a line
    protocol to the agent (write_file / run / read_file / read_logs) — this needs NO TAP, so
    host↔guest control works even on a locked-down host.
  * Node↔node networking = a host bridge + one TAP per VM (this is the part that needs CAP_NET_ADMIN).
    Peers get the same PORT / PEER_<NAME>_HOST/PORT contract as the other providers, injected into
    the guest agent's environment; `[[links]]` shaping/firewall apply with tc/iptables on the host
    TAPs (host-side, same primitives as docker.py's sidecar).
"""
from __future__ import annotations

import os
import shutil

from .base import EnvironmentProvider, EnvSpec, NodeSpec
from .capabilities import PROVIDER_CAPS, Capabilities

FC_BIN = os.environ.get("PEAKSTONE_FC_BIN", "firecracker")
FC_KERNEL = os.environ.get("PEAKSTONE_FC_KERNEL", "")   # path to a guest vmlinux
FC_ROOTFS = os.environ.get("PEAKSTONE_FC_ROOTFS", "")   # path to a guest ext4 rootfs (with the agent)
GUEST_MEM_MIB = int(os.environ.get("PEAKSTONE_FC_MEM_MIB", "256"))
GUEST_VCPUS = int(os.environ.get("PEAKSTONE_FC_VCPUS", "1"))

CAP_NET_ADMIN = 12   # bit position in the capability bitmask


class UnsupportedHost(RuntimeError):
    """The host can't run Firecracker (see .reasons)."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("host cannot run Firecracker microVMs: " + "; ".join(reasons))


def _can_open_rw(path: str) -> bool:
    try:
        fd = os.open(path, os.O_RDWR)
        os.close(fd)
        return True
    except OSError:
        return False


def _has_cap_net_admin() -> bool:
    """Read the effective capability set from /proc — TAP devices need CAP_NET_ADMIN."""
    try:
        for line in open("/proc/self/status"):
            if line.startswith("CapEff:"):
                return bool(int(line.split()[1], 16) & (1 << CAP_NET_ADMIN))
    except OSError:
        pass
    return False


def host_prereqs() -> list[str]:
    """Missing host capabilities (empty == this host can run Firecracker)."""
    missing = []
    if not shutil.which(FC_BIN):
        missing.append(f"firecracker binary ({FC_BIN!r}) not on PATH")
    if not _can_open_rw("/dev/kvm"):
        missing.append("/dev/kvm not accessible (join the 'kvm' group or run as root)")
    if not (os.path.exists("/dev/net/tun") and _has_cap_net_admin()):
        missing.append("CAP_NET_ADMIN + /dev/net/tun required for guest TAP networking")
    return missing


def vm_config(node: NodeSpec, *, rootfs: str, kernel: str, tap: str, guest_mac: str) -> dict:
    """The Firecracker machine config for one node (PUT to the API socket pre-boot). Pure + tested."""
    return {
        "boot-source": {
            "kernel_image_path": kernel,
            "boot_args": "console=ttyS0 reboot=k panic=1 pci=off ip=dhcp",
        },
        "drives": [{
            "drive_id": "rootfs", "path_on_host": rootfs,
            "is_root_device": True, "is_read_only": False,
        }],
        "machine-config": {"vcpu_count": GUEST_VCPUS, "mem_size_mib": GUEST_MEM_MIB},
        # control plane: vsock (no TAP needed) for the guest-agent exec protocol
        "vsock": {"guest_cid": 3, "uds_path": f"/tmp/ps-fc-{node.name}.vsock"},
        # data plane: one TAP per VM on the host bridge for node↔node traffic
        "network-interfaces": [{
            "iface_id": "eth0", "host_dev_name": tap, "guest_mac": guest_mac,
        }],
    }


class FirecrackerProvider(EnvironmentProvider):
    name = "microvm"

    def available(self) -> bool:
        return not host_prereqs()

    def capabilities(self) -> Capabilities:
        return PROVIDER_CAPS["microvm"]

    def provision(self, spec: EnvSpec):
        reasons = host_prereqs()
        if not FC_KERNEL or not os.path.exists(FC_KERNEL):
            reasons.append("guest kernel missing (set PEAKSTONE_FC_KERNEL to a vmlinux)")
        if not FC_ROOTFS or not os.path.exists(FC_ROOTFS):
            reasons.append("guest rootfs missing (set PEAKSTONE_FC_ROOTFS to an ext4 image with the agent)")
        if reasons:
            raise UnsupportedHost(reasons)
        # A KVM+TAP host with a kernel+rootfs reaches here; boot + the vsock guest-agent exec layer
        # is the remaining implementation (see module docstring).
        raise NotImplementedError(
            "Firecracker boot + vsock guest-agent exec not yet implemented; host prerequisites are "
            "met — wire up the API-socket boot and the guest agent to finish this provider.")
