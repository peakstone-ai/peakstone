"""Network capability model for goal-state-env challenges (PLAN.md §9 P3).

A challenge declares the network *requirements* its test is only valid under — egress blocked, real
DNS, a public IP, UDP, a shaped or firewalled link. A provider advertises the *capabilities* it can
offer, each at a fidelity: a docker `internal:` network really blocks egress (real), but netem
latency is an approximation (simulated). `match()` decides whether a provider satisfies a challenge
and at what overall fidelity, which does two jobs:

  1. selection — pick the cheapest provider that actually satisfies the requirements;
  2. provenance + trust — a result produced under *simulated* conditions is not comparable to one
     under *real* conditions, so the fidelity is recorded and caps the trust tier.

Scope is deliberately limited to **locally-controlled, reproducible** providers: local (now),
docker, and microvm (deferred impl). Real external hosts (a true public IP, real recursive DNS) are
**intentionally out of scope** — they'd give genuine real-world conditions but destroy
reproducibility, which is the platform's whole point. So PUBLIC_IP / REAL_DNS remain in the
vocabulary (a challenge can express them), but no supported provider offers them: such a challenge
is reported unsatisfiable-by-design rather than silently run under weaker conditions.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- capability keys (what a network requirement reduces to) -------------------------------------
EGRESS_CONTROL = "egress_control"      # can block/allow internet egress deterministically
INTERNAL_DNS = "internal_dns"          # service-name resolution between nodes
REAL_DNS = "real_dns"                  # real recursive resolver (public names)
PUBLIC_IP = "public_ip"                # a routable public address
UDP = "udp"
ICMP = "icmp"
LINK_SHAPING = "link_shaping"          # latency / loss / bandwidth on a link
FIREWALL = "firewall"                  # block traffic between specific nodes
NAT = "nat"                            # NAT on a path
KERNEL_ISOLATION = "kernel_isolation"  # real kernel boundary for untrusted agent code


# --- what a challenge declares -------------------------------------------------------------------
@dataclass
class Link:
    src: str
    dst: str
    latency_ms: float | None = None
    loss: float | None = None
    bandwidth_kbps: int | None = None
    firewall: str | None = None        # "blocked" | "open"
    nat: bool = False


@dataclass
class NodeNet:
    public_ip: bool = False
    transports: list[str] = field(default_factory=lambda: ["tcp"])


@dataclass
class Requirements:
    egress: str | None = None          # "blocked" | "allowed" | None (don't care)
    dns: str | None = None             # "internal" | "real" | None
    nodes: dict[str, NodeNet] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not required_caps(self)

    def summary(self) -> dict:
        return {"egress": self.egress, "dns": self.dns, "required_caps": sorted(required_caps(self)),
                "links": [{"src": l.src, "dst": l.dst, "latency_ms": l.latency_ms, "loss": l.loss,
                           "bandwidth_kbps": l.bandwidth_kbps, "firewall": l.firewall, "nat": l.nat}
                          for l in self.links]}


def required_caps(req: Requirements) -> set[str]:
    """Reduce declared requirements to the set of capability keys a provider must support."""
    caps: set[str] = set()
    if req.egress in ("blocked", "allowed"):
        caps.add(EGRESS_CONTROL)
    if req.dns == "internal":
        caps.add(INTERNAL_DNS)
    if req.dns == "real":
        caps.add(REAL_DNS)
    for n in req.nodes.values():
        if n.public_ip:
            caps.add(PUBLIC_IP)
        if "udp" in n.transports:
            caps.add(UDP)
        if "icmp" in n.transports:
            caps.add(ICMP)
    for l in req.links:
        if l.latency_ms or l.loss or l.bandwidth_kbps:
            caps.add(LINK_SHAPING)
        if l.firewall == "blocked":
            caps.add(FIREWALL)
        if l.nat:
            caps.add(NAT)
    return caps


# --- what a provider advertises ------------------------------------------------------------------
@dataclass
class Capabilities:
    provider: str
    cost: int                          # selection preference (lower = cheaper/faster)
    isolation: str                     # process | container | vm | host
    supported: dict[str, str]          # capability key -> "real" | "simulated"


@dataclass
class MatchResult:
    provider: str
    ok: bool
    unmet: list[str]                   # capability keys the provider can't satisfy
    fidelity: str                      # "real" | "simulated" | "n/a" (no network conditions required)


def match(req: Requirements, caps: Capabilities) -> MatchResult:
    needed = required_caps(req)
    unmet = sorted(k for k in needed if k not in caps.supported)
    fids = {caps.supported[k] for k in needed if k in caps.supported}
    fidelity = "n/a" if not fids else ("simulated" if "simulated" in fids else "real")
    return MatchResult(caps.provider, not unmet, unmet, fidelity)


# Advertised capability table — only reproducible providers. local/docker have provision() impls;
# microvm is advertised so the matcher can reason about it today (impl deferred). microvm adds
# KERNEL_ISOLATION (a real kernel boundary for untrusted agent code) over docker; link shaping is
# "simulated" (netem) on both. PUBLIC_IP / REAL_DNS appear in NO provider — see module docstring:
# real-host providers are excluded by design to preserve reproducibility.
PROVIDER_CAPS: dict[str, Capabilities] = {
    "local": Capabilities("local", 0, "process", {UDP: "real"}),
    "docker": Capabilities("docker", 1, "container", {
        EGRESS_CONTROL: "real", INTERNAL_DNS: "real", UDP: "real", ICMP: "real",
        FIREWALL: "real", NAT: "real", LINK_SHAPING: "simulated"}),
    # microvm: isolated bridge → real egress control; /etc/hosts → internal DNS; real kernel
    # boundary. Firewall/link-shaping need host-side tc/iptables on the taps (CAP_NET_ADMIN) and
    # aren't wired yet → not advertised, so link-condition challenges route to docker.
    "microvm": Capabilities("microvm", 2, "vm", {
        EGRESS_CONTROL: "real", INTERNAL_DNS: "real", UDP: "real", ICMP: "real",
        KERNEL_ISOLATION: "real"}),
}

# Capabilities intentionally unsupported (would require non-reproducible external hosts). A challenge
# requiring one of these is unsatisfiable by design.
NON_REPRODUCIBLE_CAPS = frozenset({PUBLIC_IP, REAL_DNS})


def select_provider(req: Requirements, allowed: list[str] | None = None) -> MatchResult | None:
    """Cheapest provider that satisfies the requirements (None if nothing can)."""
    keys = allowed or list(PROVIDER_CAPS)
    for caps in sorted((PROVIDER_CAPS[k] for k in keys), key=lambda c: c.cost):
        m = match(req, caps)
        if m.ok:
            return m
    return None
