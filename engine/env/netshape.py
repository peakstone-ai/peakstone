"""tc/netem command builders for per-link network shaping (PLAN.md §9 P3).

Pure functions so they're unit-testable without any container/VM. A single source can shape several
links to different destinations: a `prio` qdisc carries unmatched traffic in band 1:1 (no delay)
and each shaped destination gets its own netem child + a u32 filter matching that dst IP. The caller
executes the returned commands inside the source's network namespace (docker: a NET_ADMIN sidecar).
"""
from __future__ import annotations


def netem_args(link) -> list[str]:
    """The `netem` arguments for one link's conditions (latency/loss/bandwidth)."""
    parts: list[str] = []
    if link.latency_ms:
        parts += ["delay", f"{int(link.latency_ms)}ms"]
    if link.loss:
        parts += ["loss", f"{link.loss * 100:.2f}%"]
    if link.bandwidth_kbps:
        parts += ["rate", f"{int(link.bandwidth_kbps)}kbit"]
    return parts


def shaping_commands(shaped_links, ip_of, iface: str = "eth0") -> list[str]:
    """tc commands to shape several links from ONE source, each to a distinct destination IP.

    `shaped_links` are Link objects (all with conditions, same src); `ip_of(name)->ip` resolves a
    peer. Band 1:1 is unshaped (default via the all-zero priomap); shaped dsts go to bands 1:2.. via
    u32 filters. Returns [] if nothing to shape."""
    links = [l for l in shaped_links if netem_args(l)]
    if not links:
        return []
    n = len(links)
    cmds = [f"tc qdisc replace dev {iface} root handle 1: prio bands {n + 1} "
            "priomap " + " ".join(["0"] * 16)]
    for i, l in enumerate(links):
        band = i + 2                       # classid 1:2 .. 1:(n+1)
        cmds.append(f"tc qdisc add dev {iface} parent 1:{band} handle {band}0: netem "
                    + " ".join(netem_args(l)))
        cmds.append(f"tc filter add dev {iface} protocol ip parent 1:0 prio {i + 1} "
                    f"u32 match ip dst {ip_of(l.dst)}/32 flowid 1:{band}")
    return cmds
