"""The docker provider doesn't just *advertise* firewall/shaping — it applies them. These run a real
listener across a 2-node topology and assert the declared conditions actually take effect. Skipped
unless a docker daemon is reachable (they also pull the netshape sidecar image on first run)."""
from __future__ import annotations

import pytest

from engine.env import EnvSpec, NodeSpec, Requirements
from engine.env.capabilities import Link
from engine.env.docker import DockerComposeProvider

pytestmark = pytest.mark.skipif(not DockerComposeProvider().available(),
                                reason="docker daemon not available")

SERVE = "python -m http.server 9000"
PROBE = ("python -c \"import socket; socket.setdefaulttimeout(3); "
         "socket.create_connection(('b', 9000))\"")


def _two_nodes(spec_id, req):
    return EnvSpec(spec_id, nodes=[NodeSpec("a", needs=["b"]), NodeSpec("b", ports=[9000])],
                   requirements=req)


def test_open_link_is_reachable_but_blocked_link_is_not():
    # control: no firewall -> a reaches b
    with DockerComposeProvider().provision(_two_nodes("net-open", Requirements())) as env:
        env.node("b").run(SERVE, background=True)
        assert env.wait_ready("b", 9000, timeout=12)
        assert env.node("a").run(PROBE, timeout=8).rc == 0

    # firewall blocked a->b -> the same probe fails, even though b is serving
    blocked = Requirements(links=[Link("a", "b", firewall="blocked")])
    with DockerComposeProvider().provision(_two_nodes("net-fw", blocked)) as env:
        assert env.provenance()["applied_network"]["firewall"][0]["ok"] is True
        env.node("b").run(SERVE, background=True)
        env.wait_ready("b", 9000, timeout=12)            # b sees its own port (localhost) fine
        assert env.node("a").run(PROBE, timeout=8).rc != 0  # but a is firewalled off


def test_per_source_multi_link_shaping():
    # one source shaping TWO destinations differently: src->a fast (~50ms), src->b slow (~300ms)
    req = Requirements(links=[Link("src", "a", latency_ms=50), Link("src", "b", latency_ms=300)])
    spec = EnvSpec("net-multi", requirements=req, nodes=[
        NodeSpec("src", needs=["a", "b"]), NodeSpec("a", ports=[9000]), NodeSpec("b", ports=[9000])])
    with DockerComposeProvider().provision(spec) as env:
        for n in ("a", "b"):
            env.node(n).run("python -m http.server 9000", background=True)
            assert env.wait_ready(n, 9000, timeout=12)

        def rtt(dst):
            meas = (f"python -c \"import socket,time; t=time.time(); "
                    f"socket.create_connection(('{dst}',9000)).close(); print(int((time.time()-t)*1000))\"")
            return int(env.node("src").run(meas, timeout=12).stdout.strip() or "0")
        ra, rb = rtt("a"), rtt("b")
        assert ra < 150 and rb >= 200, f"src->a={ra}ms src->b={rb}ms (expected ~50 vs ~300)"


def test_link_latency_is_applied_and_measurable():
    req = Requirements(links=[Link("a", "b", latency_ms=200)])
    with DockerComposeProvider().provision(_two_nodes("net-lat", req)) as env:
        shaping = env.provenance()["applied_network"]["shaping"]
        assert shaping and shaping[0]["ok"] and "delay 200ms" in shaping[0]["netem"]
        env.node("b").run(SERVE, background=True)
        env.wait_ready("b", 9000, timeout=12)
        meas = ("python -c \"import socket,time; t=time.time(); "
                "socket.create_connection(('b',9000)).close(); print(int((time.time()-t)*1000))\"")
        rtt_ms = int(env.node("a").run(meas, timeout=12).stdout.strip() or "0")
        assert rtt_ms >= 150, f"expected ~200ms netem delay, measured {rtt_ms}ms"
