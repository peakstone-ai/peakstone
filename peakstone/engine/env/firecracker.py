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
# Default sized for the TEST sandbox: real compilers (go/rust/cgo) and the scientific Python stack
# OOM at the old 256 MiB. 4 GiB / 2 vCPUs runs them comfortably; override down for lightweight
# agentic-env nodes (PEAKSTONE_FC_MEM_MIB) or up for a memory-hungry crate.
GUEST_MEM_MIB = int(os.environ.get("PEAKSTONE_FC_MEM_MIB", "4096"))
GUEST_VCPUS = int(os.environ.get("PEAKSTONE_FC_VCPUS", "2"))
GUEST_CID = 3
AGENT_PORT = 1024   # must match engine/env/firecracker_agent (the guest agent)

# Node↔node networking (Milestone 2): an isolated host bridge + a pool of persistent, user-owned
# TAPs (created once by fc-net-setup.sh as root). The harness only *attaches* VMs to existing taps,
# which needs no CAP_NET_ADMIN. The bridge has no uplink → guests have no internet (egress blocked).
FC_BRIDGE = os.environ.get("PEAKSTONE_FC_BRIDGE", "psfc-br0")
FC_TAP_PREFIX = os.environ.get("PEAKSTONE_FC_TAP_PREFIX", "psfc-tap")
FC_SUBNET = os.environ.get("PEAKSTONE_FC_SUBNET", "172.30.0")   # /24; bridge is .1, guests .10+
GUEST_IP_BASE = 10

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


def _iface_exists(name: str) -> bool:
    return os.path.exists(f"/sys/class/net/{name}")


def _tap_owner(name: str) -> int | None:
    """uid that owns a tun/tap device (sysfs `owner`); None for a missing/non-tap interface."""
    try:
        with open(f"/sys/class/net/{name}/owner") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def available_taps() -> list[str]:
    """Pre-created taps from the pool (fc-net-setup.sh) that WE own, in order. Ownership is part of
    the contract: Firecracker can open a pre-existing tap without CAP_NET_ADMIN only when this uid
    owns it — a root-owned pool (e.g. from a systemd unit missing PEAKSTONE_FC_TAP_USER) makes every
    networked boot die with EPERM, so such taps are excluded here (and host_prereqs names them)."""
    taps = []
    i = 0
    while _iface_exists(f"{FC_TAP_PREFIX}{i}"):
        if _tap_owner(f"{FC_TAP_PREFIX}{i}") == os.geteuid():
            taps.append(f"{FC_TAP_PREFIX}{i}")
        i += 1
    return taps


def host_prereqs(*, networking: bool = True) -> list[str]:
    """Missing host capabilities (empty == this host can run Firecracker). `networking=False` is the
    vsock-only single-node mode (no TAP at all). With networking, we use pre-created user-owned taps,
    so no CAP_NET_ADMIN is needed at runtime — only that the bridge + tap pool exist."""
    missing = []
    if not _binary_ok():
        missing.append(f"firecracker binary ({FC_BIN!r}) not found")
    if not _can_open_rw("/dev/kvm"):
        missing.append("/dev/kvm not accessible (join the 'kvm' group or run as root)")
    setup = "peakstone/engine/env/firecracker_agent/fc-net-setup.sh"
    if networking and not _iface_exists(FC_BRIDGE):
        missing.append(f"bridge {FC_BRIDGE!r} missing — run {setup}")
    if networking and not available_taps():
        first = f"{FC_TAP_PREFIX}0"
        if _iface_exists(first):
            missing.append(f"{FC_TAP_PREFIX}* taps are owned by uid {_tap_owner(first)}, not "
                           f"{os.geteuid()} — re-run {setup} (it repairs ownership)")
        else:
            missing.append(f"no {FC_TAP_PREFIX}* taps — run {setup}")
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
        reader = _LineReader(s)   # buffers across reads — the ack and the JSON reply may share a recv
        s.sendall(f"CONNECT {port}\n".encode())
        ack = reader.readline()
        if not ack.startswith("OK"):
            return {"error": f"vsock CONNECT refused: {ack!r}"}
        s.sendall(json.dumps(req).encode() + b"\n")
        return json.loads(reader.readline() or "{}")
    finally:
        s.close()


class _LineReader:
    """Newline-framed reader that keeps bytes received past a line boundary, so the CONNECT ack and
    the JSON response don't desync when they arrive in the same packet."""
    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._buf = bytearray()

    def readline(self) -> str:
        while b"\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                break
            self._buf.extend(chunk)
        line, sep, rest = bytes(self._buf).partition(b"\n")
        self._buf = bytearray(rest)
        return line.decode("utf-8", "replace")


class FirecrackerNode(Node):
    def __init__(self, name: str, uds_path: str, ip: str | None = None, env: dict | None = None):
        self.name = name
        self._uds = uds_path
        self._ip = ip
        self._env = env or {}      # PORT / PEER_<NAME>_HOST/PORT, injected into every run

    @property
    def host(self) -> str:
        return self._ip or self.name

    def _req(self, req: dict, timeout: float = 30.0) -> dict:
        return vsock_request(self._uds, AGENT_PORT, req, timeout=timeout)

    def write_file(self, path: str, content: str) -> dict:
        return self._req({"op": "write", "path": path, "content": content})

    def read_file(self, path: str) -> dict:
        return self._req({"op": "read", "path": path})

    def run(self, cmd: str, *, background: bool = False, timeout: int = 30, _env: dict | None = None) -> RunResult:
        env = {**self._env, **(_env or {})}
        r = self._req({"op": "run", "cmd": cmd, "background": background, "timeout": timeout,
                       "env": env}, timeout=timeout + 5)
        if "error" in r:
            return RunResult(127, "", r["error"])
        return RunResult(r.get("rc", 0), r.get("stdout", ""), r.get("stderr", ""),
                         timed_out=bool(r.get("timed_out")))

    def read_logs(self) -> str:
        r = self._req({"op": "read", "path": "/work/.bglog"})
        return f"--- {self.name} ---\n{r.get('content', '')}" if "content" in r else ""


class FirecrackerEnvironment(Environment):
    provider_name = "microvm"

    def __init__(self, spec: EnvSpec, *, networked: bool):
        self.spec = spec
        self._networked = networked
        self._dir = Path(tempfile.mkdtemp(prefix=f"psfc-{spec.id}-"))
        self._procs: list[subprocess.Popen] = []
        self.nodes: dict[str, Node] = {}
        # assign a tap + IP per node from the pool (networked runs only)
        self._ip: dict[str, str] = {}
        self._tap: dict[str, str] = {}
        self._applied_net: dict = {}
        try:
            if networked:
                taps = available_taps()
                if len(taps) < len(spec.nodes):
                    raise UnsupportedHost([f"need {len(spec.nodes)} taps, pool has {len(taps)} "
                                           f"({FC_TAP_PREFIX}*) — grow it in fc-net-setup.sh"])
                for i, n in enumerate(spec.nodes):
                    self._ip[n.name] = f"{FC_SUBNET}.{GUEST_IP_BASE + i}"
                    self._tap[n.name] = taps[i]
            for n in spec.nodes:
                self._boot(n)
            if networked:
                self._configure_network()
        except BaseException:
            self.teardown()   # don't leak booted VMs / temp dir / vsock sockets on partial failure
            raise

    def _node_env(self, n: NodeSpec) -> dict:
        env: dict[str, str] = {}
        if n.ports:
            env["PORT"] = str(n.ports[0])
            env["PORTS"] = ",".join(str(p) for p in n.ports)
        for peer in n.needs:
            env[f"PEER_{peer.upper()}_HOST"] = peer          # resolvable via injected /etc/hosts
            pspec = self.spec.node_map.get(peer)
            if pspec and pspec.ports:
                env[f"PEER_{peer.upper()}_PORT"] = str(pspec.ports[0])
        return env

    def _boot(self, n: NodeSpec) -> None:
        uds = str(self._dir / f"{n.name}.vsock")
        rootfs = str(self._dir / f"{n.name}.ext4")
        shutil.copyfile(FC_ROOTFS, rootfs)   # per-VM writable copy of the base image
        mac = None
        if self._networked:
            last = int(self._ip[n.name].rsplit(".", 1)[1])
            mac = f"06:00:AC:1E:00:{last:02x}"
        cfg = vm_config(n, rootfs=rootfs, kernel=FC_KERNEL, uds_path=uds,
                        tap=self._tap.get(n.name), guest_mac=mac)
        cfg_path = self._dir / f"{n.name}.json"
        cfg_path.write_text(json.dumps(cfg))
        log = open(self._dir / f"{n.name}.console", "wb")
        p = subprocess.Popen([FC_BIN, "--no-api", "--config-file", str(cfg_path)],
                             stdout=log, stderr=subprocess.STDOUT, cwd=self._dir)
        self._procs.append(p)
        self.nodes[n.name] = FirecrackerNode(n.name, uds, ip=self._ip.get(n.name),
                                             env=self._node_env(n))
        self._wait_agent(n.name, uds, p, deadline=time.monotonic() + 30)

    def _configure_network(self) -> None:
        """Bring up each guest's eth0 with its assigned IP and a hosts file so peers resolve by name."""
        hosts = "127.0.0.1 localhost\n" + "".join(f"{self._ip[n]} {n}\n" for n in self._ip)
        for n in self.spec.nodes:
            node = self.nodes[n.name]
            ip = self._ip[n.name]
            # lo must be up too (a minimal init=agent boot leaves it down → 127.0.0.1 unreachable)
            r = node.run(f"ip link set lo up && ip addr add {ip}/24 dev eth0 && ip link set eth0 up",
                         timeout=10)
            if r.rc != 0:
                raise RuntimeError(f"network config failed on '{n.name}': {r.stderr or r.stdout}")
            node.write_file("/etc/hosts", hosts)
        self._applied_net = self._apply_links()

    def _apply_links(self) -> dict:
        """Apply [[links]] conditions IN-GUEST (each microVM is root in its own kernel, so no host
        privilege needed). Firewall = blackhole routes; netem shaping is unavailable (the CI guest
        kernel has no sch_netem) so latency/loss links are recorded as skipped and route to docker."""
        applied: dict = {"firewall": [], "shaping": []}
        for l in self.spec.requirements.links:
            if l.firewall == "blocked":
                a, b = self._ip.get(l.src), self._ip.get(l.dst)
                if a and b:
                    ok = (self.nodes[l.src].run(f"ip route add blackhole {b}/32", timeout=8).rc == 0
                          and self.nodes[l.dst].run(f"ip route add blackhole {a}/32", timeout=8).rc == 0)
                    applied["firewall"].append({"src": l.src, "dst": l.dst, "ok": ok})
            if l.latency_ms or l.loss or l.bandwidth_kbps:
                applied["shaping"].append({"src": l.src, "dst": l.dst,
                                           "skipped": "guest kernel lacks sch_netem (shaping routes to docker)"})
        return applied

    def _wait_agent(self, name: str, uds: str, proc: subprocess.Popen, deadline: float) -> None:
        while time.monotonic() < deadline:
            if proc.poll() is not None:   # firecracker died (kernel panic / bad config) — fail fast
                raise RuntimeError(f"firecracker for '{name}' exited rc={proc.returncode} "
                                   f"(see {self._dir}/{name}.console)")
            if os.path.exists(uds):
                r = vsock_request(uds, AGENT_PORT, {"op": "ping"}, timeout=3)
                if r.get("ok"):
                    return
            time.sleep(0.3)
        raise RuntimeError(f"guest agent on '{name}' never became ready "
                           f"(see {self._dir}/{name}.console)")

    def address_of(self, name: str) -> tuple[str, int | None]:
        spec = self.spec.node_map.get(name)
        return (self._ip.get(name, name), spec.ports[0] if spec and spec.ports else None)

    def wait_ready(self, name: str, port: int, timeout: float = 10.0) -> bool:
        if not self._networked:
            return True
        # probe from inside the node itself (server binds locally); the host bridge could also reach it
        probe = (f"python3 -c \"import socket; socket.setdefaulttimeout(1); "
                 f"socket.create_connection(('127.0.0.1', {port}))\"")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.nodes[name].run(probe, timeout=4).rc == 0:
                return True
            time.sleep(0.3)
        return False

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
        p = {"provider": "microvm", "kernel": FC_KERNEL, "rootfs": FC_ROOTFS,
             "vcpus": GUEST_VCPUS, "mem_mib": GUEST_MEM_MIB}
        if self._networked:
            p["network"] = {"bridge": FC_BRIDGE, "subnet": f"{FC_SUBNET}.0/24",
                            "nodes": dict(self._ip)}
            p["applied_network"] = self._applied_net
        return p


class FirecrackerProvider(EnvironmentProvider):
    name = "microvm"

    def available(self) -> bool:
        # vsock-only (single-node exec) is the implemented path; it needs no TAP networking
        return not host_prereqs(networking=False)

    def capabilities(self) -> Capabilities:
        return PROVIDER_CAPS["microvm"]

    def provision(self, spec: EnvSpec) -> FirecrackerEnvironment:
        # vsock-only exec needs no networking; >1 node (or any node with ports/needs) uses the
        # pre-created bridge + tap pool (Milestone 2).
        needs_net = len(spec.nodes) > 1 or any(n.ports or n.needs for n in spec.nodes)
        reasons = host_prereqs(networking=needs_net)
        if not os.path.exists(FC_KERNEL):
            reasons.append(f"guest kernel missing ({FC_KERNEL}); set PEAKSTONE_FC_KERNEL")
        if not os.path.exists(FC_ROOTFS):
            reasons.append(f"guest rootfs missing ({FC_ROOTFS}); set PEAKSTONE_FC_ROOTFS")
        if reasons:
            raise UnsupportedHost(reasons)
        return FirecrackerEnvironment(spec, networked=needs_net)
