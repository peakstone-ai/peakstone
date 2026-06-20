"""Firecracker microVM EnvironmentProvider (PLAN.md §9 P3) — SCAFFOLD.

Why a microVM tier at all: docker already gives real DNS/firewall/NAT/egress control (see docker.py),
so the microVM's headline win is **isolation**, not network realism — a real kernel boundary for the
untrusted, model-generated agent code, plus kernel-level fidelity (own netfilter, raw sockets,
sysctls) that containers restrict. Same EnvSpec / Node interface as the other providers.

STATUS:
  * Milestone 1 (DONE, verified on hardware): single-node, vsock-only exec. `provision()` boots a
    real microVM per node via `firecracker --no-api --config-file`, with our Go guest agent
    (engine/env/firecracker_agent) as PID 1 over vsock — write_file / read_file / run / read_logs.
    Needs only /dev/kvm + the binary + a kernel/rootfs (no TAP, no CAP_NET_ADMIN). Boots in ~1s.
  * Milestone 2 (TODO): node↔node TAP networking, so multi-node challenges with [[links]] run. A
    spec with >1 node (or any node with ports/needs) is refused until this lands.

Architecture:
  * One microVM per node. Boot from a config file (boot-source vmlinux + `init=/usr/local/bin/ps-agent`,
    a per-VM writable ext4 copy, vcpu/mem, vsock). A read-only base + overlay and the jailer are
    future hardening.
  * Exec = the guest agent over vsock (Firecracker hybrid vsock UDS). The host sends `CONNECT <port>`
    then newline-JSON requests — no TAP needed, so host↔guest control works on a locked-down host.
  * Node↔node networking (M2) = a host bridge + one TAP per VM (the part that needs CAP_NET_ADMIN, or
    pre-created user-owned persistent taps). Peers get the same PORT / PEER_<NAME>_HOST/PORT contract;
    `[[links]]` shaping/firewall apply with tc/iptables on the host TAPs (same primitives as docker.py).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from .base import Environment, EnvironmentProvider, EnvSpec, Node, NodeSpec, RunResult
from .capabilities import PROVIDER_CAPS, Capabilities

FC_HOME = Path(os.environ.get("PEAKSTONE_FC_HOME", str(Path.home() / ".peakstone" / "fc")))
FC_BIN = os.environ.get("PEAKSTONE_FC_BIN") or (str(FC_HOME / "firecracker")
                                                if (FC_HOME / "firecracker").exists() else "firecracker")
FC_KERNEL = os.environ.get("PEAKSTONE_FC_KERNEL") or str(FC_HOME / "vmlinux")
FC_ROOTFS = os.environ.get("PEAKSTONE_FC_ROOTFS") or str(FC_HOME / "rootfs.ext4")
GUEST_MEM_MIB = int(os.environ.get("PEAKSTONE_FC_MEM_MIB", "256"))
GUEST_VCPUS = int(os.environ.get("PEAKSTONE_FC_VCPUS", "1"))
GUEST_CID = 3
AGENT_PORT = 1024   # must match engine/env/firecracker_agent (the guest agent)

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


def _binary_ok() -> bool:
    return bool(shutil.which(FC_BIN) or os.path.exists(FC_BIN))


def host_prereqs(*, networking: bool = True) -> list[str]:
    """Missing host capabilities (empty == this host can run Firecracker). `networking=False` is the
    vsock-only single-node mode, which needs neither TAP nor CAP_NET_ADMIN."""
    missing = []
    if not _binary_ok():
        missing.append(f"firecracker binary ({FC_BIN!r}) not found")
    if not _can_open_rw("/dev/kvm"):
        missing.append("/dev/kvm not accessible (join the 'kvm' group or run as root)")
    if networking and not (os.path.exists("/dev/net/tun") and _has_cap_net_admin()):
        missing.append("CAP_NET_ADMIN + /dev/net/tun required for guest TAP networking "
                       "(or pre-create user-owned persistent taps)")
    return missing


def vm_config(node: NodeSpec, *, rootfs: str, kernel: str, uds_path: str,
              tap: str | None = None, guest_mac: str | None = None) -> dict:
    """The Firecracker machine config for one node. vsock is the control plane (exec, no TAP needed);
    a TAP network-interface is added only when given (multi-node data plane)."""
    cfg = {
        "boot-source": {
            "kernel_image_path": kernel,
            # init=ps-agent: our guest agent is PID 1 (fast, no systemd). panic=1+reboot=k so a guest
            # fault stops the VM instead of hanging.
            "boot_args": "console=ttyS0 reboot=k panic=1 pci=off init=/usr/local/bin/ps-agent",
        },
        "drives": [{
            "drive_id": "rootfs", "path_on_host": rootfs,
            "is_root_device": True, "is_read_only": False,
        }],
        "machine-config": {"vcpu_count": GUEST_VCPUS, "mem_size_mib": GUEST_MEM_MIB},
        "vsock": {"guest_cid": GUEST_CID, "uds_path": uds_path},
    }
    if tap:
        cfg["network-interfaces"] = [{"iface_id": "eth0", "host_dev_name": tap, "guest_mac": guest_mac}]
    return cfg


def vsock_request(uds_path: str, port: int, req: dict, *, timeout: float = 30.0) -> dict:
    """One request to the guest agent through Firecracker's vsock UDS. The hybrid-vsock protocol:
    connect to the UDS, send `CONNECT <port>\\n`, read `OK ...`, then exchange newline-JSON."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(uds_path)
        s.sendall(f"CONNECT {port}\n".encode())
        ack = _read_line(s)
        if not ack.startswith("OK"):
            return {"error": f"vsock CONNECT refused: {ack!r}"}
        s.sendall(json.dumps(req).encode() + b"\n")
        return json.loads(_read_line(s) or "{}")
    finally:
        s.close()


def _read_line(s: socket.socket) -> str:
    buf = bytearray()
    while b"\n" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf.extend(chunk)
    return buf.split(b"\n", 1)[0].decode("utf-8", "replace")


class FirecrackerNode(Node):
    def __init__(self, name: str, uds_path: str, spec: EnvSpec):
        self.name = name
        self._uds = uds_path
        self._spec = spec

    @property
    def host(self) -> str:
        return self.name

    def _req(self, req: dict, timeout: float = 30.0) -> dict:
        return vsock_request(self._uds, AGENT_PORT, req, timeout=timeout)

    def write_file(self, path: str, content: str) -> dict:
        return self._req({"op": "write", "path": path, "content": content})

    def read_file(self, path: str) -> dict:
        return self._req({"op": "read", "path": path})

    def run(self, cmd: str, *, background: bool = False, timeout: int = 30) -> RunResult:
        r = self._req({"op": "run", "cmd": cmd, "background": background, "timeout": timeout},
                      timeout=timeout + 5)
        if "error" in r:
            return RunResult(127, "", r["error"])
        return RunResult(r.get("rc", 0), r.get("stdout", ""), r.get("stderr", ""),
                         timed_out=bool(r.get("timed_out")))

    def read_logs(self) -> str:
        r = self._req({"op": "read", "path": "/work/.bglog"})
        return f"--- {self.name} ---\n{r.get('content', '')}" if "content" in r else ""


class FirecrackerEnvironment(Environment):
    provider_name = "microvm"

    def __init__(self, spec: EnvSpec):
        self.spec = spec
        self._dir = Path(tempfile.mkdtemp(prefix=f"psfc-{spec.id}-"))
        self._procs: list[subprocess.Popen] = []
        self.nodes: dict[str, Node] = {}
        for n in spec.nodes:
            self._boot(n)

    def _boot(self, n: NodeSpec) -> None:
        uds = str(self._dir / f"{n.name}.vsock")
        rootfs = str(self._dir / f"{n.name}.ext4")
        shutil.copyfile(FC_ROOTFS, rootfs)   # per-VM writable copy of the base image
        cfg = vm_config(n, rootfs=rootfs, kernel=FC_KERNEL, uds_path=uds)
        cfg_path = self._dir / f"{n.name}.json"
        cfg_path.write_text(json.dumps(cfg))
        log = open(self._dir / f"{n.name}.console", "wb")
        p = subprocess.Popen([FC_BIN, "--no-api", "--config-file", str(cfg_path)],
                             stdout=log, stderr=subprocess.STDOUT, cwd=self._dir)
        self._procs.append(p)
        self.nodes[n.name] = FirecrackerNode(n.name, uds, self.spec)
        self._wait_agent(n.name, uds, deadline=time.monotonic() + 30)

    def _wait_agent(self, name: str, uds: str, deadline: float) -> None:
        while time.monotonic() < deadline:
            if os.path.exists(uds):
                r = vsock_request(uds, AGENT_PORT, {"op": "ping"}, timeout=3)
                if r.get("ok"):
                    return
            time.sleep(0.3)
        raise RuntimeError(f"guest agent on '{name}' never became ready "
                           f"(see {self._dir}/{name}.console)")

    def address_of(self, name: str) -> tuple[str, int | None]:
        spec = self.spec.node_map.get(name)
        return (name, spec.ports[0] if spec and spec.ports else None)

    def wait_ready(self, name: str, port: int, timeout: float = 10.0) -> bool:
        return True   # single-node milestone: node↔node networking not yet wired

    def reset(self) -> None:
        for n in self.spec.nodes:
            self.nodes[n.name].run("pkill -9 -f '[s]h -c' 2>/dev/null; true")

    def teardown(self) -> None:
        for p in self._procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
        shutil.rmtree(self._dir, ignore_errors=True)

    def provenance(self) -> dict:
        return {"provider": "microvm", "kernel": FC_KERNEL, "rootfs": FC_ROOTFS,
                "vcpus": GUEST_VCPUS, "mem_mib": GUEST_MEM_MIB}


class FirecrackerProvider(EnvironmentProvider):
    name = "microvm"

    def available(self) -> bool:
        # vsock-only (single-node exec) is the implemented path; it needs no TAP networking
        return not host_prereqs(networking=False)

    def capabilities(self) -> Capabilities:
        return PROVIDER_CAPS["microvm"]

    def provision(self, spec: EnvSpec) -> FirecrackerEnvironment:
        # Milestone 1: vsock-only exec. Node↔node TAP networking (and thus multi-node challenges with
        # [[links]]) is the next milestone — refuse rather than boot VMs that can't reach each other.
        needs_net = len(spec.nodes) > 1 or any(n.ports or n.needs for n in spec.nodes)
        reasons = host_prereqs(networking=needs_net)
        if not os.path.exists(FC_KERNEL):
            reasons.append(f"guest kernel missing ({FC_KERNEL}); set PEAKSTONE_FC_KERNEL")
        if not os.path.exists(FC_ROOTFS):
            reasons.append(f"guest rootfs missing ({FC_ROOTFS}); set PEAKSTONE_FC_ROOTFS")
        if needs_net:
            reasons.append("multi-node TAP networking not yet implemented (Milestone 2)")
        if reasons:
            raise UnsupportedHost(reasons)
        return FirecrackerEnvironment(spec)
