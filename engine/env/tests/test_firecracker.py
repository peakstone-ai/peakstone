"""Firecracker provider scaffold — hermetic checks that don't require a microVM to boot.

The boot/exec path needs a KVM-capable host with CAP_NET_ADMIN (this CI box has neither), so those
aren't tested here; what IS tested is that the provider detects its prerequisites honestly, refuses
cleanly when they're missing, and assembles a well-formed VM config.
"""
from __future__ import annotations

import pytest

from engine.env import get_provider
from engine.env.base import NodeSpec
from engine.env.capabilities import KERNEL_ISOLATION, PROVIDER_CAPS
from engine.env.firecracker import (FirecrackerProvider, UnsupportedHost, host_prereqs, vm_config)


def test_get_provider_resolves_microvm():
    assert isinstance(get_provider("microvm"), FirecrackerProvider)
    assert isinstance(get_provider("firecracker"), FirecrackerProvider)


def test_capabilities_include_kernel_isolation():
    caps = FirecrackerProvider().capabilities()
    assert caps is PROVIDER_CAPS["microvm"]
    assert caps.supported.get(KERNEL_ISOLATION) == "real"   # the microVM's headline advantage
    assert caps.isolation == "vm"


def test_available_matches_prereqs():
    p = FirecrackerProvider()
    assert p.available() == (not host_prereqs())


def test_provision_refuses_without_prereqs():
    # this host lacks kvm-group access / CAP_NET_ADMIN, so provisioning must raise with reasons
    if FirecrackerProvider().available():
        pytest.skip("host can actually run Firecracker; refusal path not exercised")
    with pytest.raises(UnsupportedHost) as ei:
        FirecrackerProvider().provision(object())  # type: ignore[arg-type]
    assert ei.value.reasons   # non-empty, explains exactly what's missing


def test_vm_config_is_well_formed():
    cfg = vm_config(NodeSpec("server", ports=[8080]),
                    rootfs="/img/rootfs.ext4", kernel="/img/vmlinux",
                    tap="ps-tap-server", guest_mac="06:00:AC:10:00:02")
    assert cfg["boot-source"]["kernel_image_path"] == "/img/vmlinux"
    assert cfg["drives"][0]["is_root_device"] is True
    assert cfg["vsock"]["uds_path"].endswith("server.vsock")        # control plane (no TAP needed)
    assert cfg["network-interfaces"][0]["host_dev_name"] == "ps-tap-server"  # data plane
    assert cfg["machine-config"]["vcpu_count"] >= 1
