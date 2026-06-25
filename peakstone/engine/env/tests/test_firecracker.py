"""Firecracker provider — hermetic checks + a real single-node boot when the host can run it.

Milestone 1 (vsock-only exec) is implemented and boots an actual microVM. The boot test runs only
where /dev/kvm + the binary + a guest kernel/rootfs are present (it's skipped on CI without them);
the rest are pure and always run.
"""
from __future__ import annotations

import os

import pytest

from peakstone.engine.env import EnvSpec, NodeSpec, get_provider
from peakstone.engine.env.capabilities import KERNEL_ISOLATION, PROVIDER_CAPS
from peakstone.engine.env.firecracker import (FC_KERNEL, FC_ROOTFS, FirecrackerProvider, UnsupportedHost,
                                    available_taps, host_prereqs, vm_config)

_CAN_BOOT = FirecrackerProvider().available() and os.path.exists(FC_KERNEL) and os.path.exists(FC_ROOTFS)
_CAN_NET = _CAN_BOOT and bool(available_taps())


def test_get_provider_resolves_microvm():
    assert isinstance(get_provider("microvm"), FirecrackerProvider)
    assert isinstance(get_provider("firecracker"), FirecrackerProvider)


def test_capabilities_include_kernel_isolation():
    caps = FirecrackerProvider().capabilities()
    assert caps is PROVIDER_CAPS["microvm"]
    assert caps.supported.get(KERNEL_ISOLATION) == "real"   # the microVM's headline advantage
    assert caps.isolation == "vm"


def test_available_tracks_vsock_only_prereqs():
    # available() reflects the implemented path (vsock-only: no TAP/CAP_NET_ADMIN needed)
    assert FirecrackerProvider().available() == (not host_prereqs(networking=False))


def test_multinode_provision_refuses_without_tap_setup():
    # >1 node needs the bridge + tap pool; without them, refuse with a pointer to the setup script
    from peakstone.engine.env.firecracker import available_taps
    if available_taps():
        pytest.skip("tap pool is set up; refusal path not exercised")
    spec = EnvSpec("fc-multi", nodes=[NodeSpec("a", needs=["b"]), NodeSpec("b", ports=[80])])
    with pytest.raises(UnsupportedHost) as ei:
        FirecrackerProvider().provision(spec)
    assert any("tap" in r or "bridge" in r or "fc-net-setup" in r for r in ei.value.reasons)


def test_vm_config_is_well_formed():
    cfg = vm_config(NodeSpec("server"), rootfs="/img/rootfs.ext4", kernel="/img/vmlinux",
                    uds_path="/tmp/server.vsock")
    assert cfg["boot-source"]["kernel_image_path"] == "/img/vmlinux"
    assert "init=/usr/local/bin/ps-agent" in cfg["boot-source"]["boot_args"]
    assert cfg["drives"][0]["is_root_device"] is True and cfg["drives"][0]["is_read_only"] is False
    assert cfg["vsock"]["uds_path"].endswith("server.vsock")
    assert "network-interfaces" not in cfg                  # vsock-only by default
    # a TAP interface is added only when given (the M2 data plane)
    assert "network-interfaces" in vm_config(NodeSpec("s"), rootfs="r", kernel="k",
                                             uds_path="u", tap="ps-tap-s", guest_mac="06:00:AC:10:00:02")


@pytest.mark.skipif(not _CAN_BOOT, reason="no /dev/kvm + firecracker binary + guest kernel/rootfs")
def test_boots_a_real_microvm_and_execs_over_vsock():
    spec = EnvSpec("fc-boot-test", nodes=[NodeSpec("vm")])   # single node -> vsock-only
    with FirecrackerProvider().provision(spec) as env:
        vm = env.node("vm")
        # the agent is PID 1 (real kernel boundary — the microVM's whole point)
        assert vm.run("cat /proc/1/comm").stdout.strip() == "ps-agent"
        assert vm.run("id -u").stdout.strip() == "0"
        assert vm.run("uname -r").stdout.strip().startswith("6.")
        # exec + file round-trip over vsock
        vm.write_file("hello.txt", "over vsock")
        assert vm.read_file("hello.txt").get("content") == "over vsock"
        r = vm.run("python3 -c 'print(6*7)'")
        assert r.rc == 0 and r.stdout.strip() == "42"
        assert env.provenance()["provider"] == "microvm"


@pytest.mark.skipif(not _CAN_NET, reason="needs kvm+artifacts AND the fc bridge/tap pool (fc-net-setup.sh)")
def test_two_microvms_communicate_over_the_bridge():
    spec = EnvSpec("fc-net", nodes=[NodeSpec("server", ports=[8000]), NodeSpec("client", needs=["server"])])
    with FirecrackerProvider().provision(spec) as env:
        s, c = env.node("server"), env.node("client")
        s.write_file("/work/data.txt", "hello over the bridge")
        s.run("cd /work && python3 -m http.server $PORT", background=True)
        assert env.wait_ready("server", 8000, timeout=20)
        # client reaches the server BY NAME (internal DNS via /etc/hosts) using the PEER_* env vars
        c.write_file("/work/fetch.py",
                     "import os,urllib.request\n"
                     "h=os.environ['PEER_SERVER_HOST']; p=os.environ['PEER_SERVER_PORT']\n"
                     "print(urllib.request.urlopen(f'http://{h}:{p}/data.txt',timeout=8).read().decode())\n")
        r = c.run("python3 /work/fetch.py")
        assert r.rc == 0 and "hello over the bridge" in r.stdout, (r.rc, r.stdout, r.stderr)
        # the isolated bridge has no uplink: egress is genuinely blocked
        egress = c.run("python3 -c \"import socket; socket.setdefaulttimeout(4); socket.create_connection(('1.1.1.1',53))\"")
        assert egress.rc != 0, "guest unexpectedly reached the internet"


@pytest.mark.skipif(not _CAN_NET, reason="needs kvm+artifacts AND the fc bridge/tap pool")
def test_microvm_firewall_blocks_a_link_in_guest():
    from peakstone.engine.env import Requirements
    from peakstone.engine.env.capabilities import Link
    req = Requirements(links=[Link("a", "b", firewall="blocked")])
    spec = EnvSpec("fc-fw", nodes=[NodeSpec("a", needs=["b"]), NodeSpec("b", ports=[9000])],
                   requirements=req)
    with FirecrackerProvider().provision(spec) as env:
        assert env.provenance()["applied_network"]["firewall"][0]["ok"] is True
        env.node("b").run("cd /work && python3 -m http.server 9000", background=True)
        env.wait_ready("b", 9000, timeout=15)
        probe = ("python3 -c \"import socket; socket.setdefaulttimeout(3); "
                 "socket.create_connection(('b',9000))\"")
        assert env.node("a").run(probe).rc != 0   # blackhole route drops a->b even with b serving
