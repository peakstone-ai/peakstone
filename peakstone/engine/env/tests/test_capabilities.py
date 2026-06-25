"""Network capability model: requirement→capability mapping, provider matching, the
reproducibility policy (no real-host providers), and capabilities-as-preconditions.

All hermetic except the docker precondition assertion (skip-gated)."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from peakstone.engine.env import (PROVIDER_CAPS, LocalProvider, Requirements, load_env_challenge, match,
                        required_caps, run_reference, select_provider)
from peakstone.engine.env.capabilities import (EGRESS_CONTROL, LINK_SHAPING, PUBLIC_IP, Link, NodeNet)
from peakstone.engine.env.docker import DockerComposeProvider
from peakstone.engine.env.harness import UnsatisfiableEnv

CH_DIR = Path(__file__).resolve().parents[4] / "challenges" / "env" / "01-file-server"


def test_requirements_reduce_to_capability_keys():
    assert required_caps(Requirements(egress="blocked")) == {EGRESS_CONTROL}
    assert required_caps(Requirements(links=[Link("a", "b", latency_ms=20)])) == {LINK_SHAPING}
    assert required_caps(Requirements(nodes={"e": NodeNet(public_ip=True)})) == {PUBLIC_IP}
    assert Requirements().empty


def test_shaping_commands_multi_link():
    # one source, two shaped destinations -> a prio qdisc + per-dst netem child + filter each
    from peakstone.engine.env.netshape import shaping_commands
    links = [Link("s", "a", latency_ms=50), Link("s", "b", latency_ms=200, loss=0.01)]
    ips = {"a": "10.0.0.2", "b": "10.0.0.3"}
    cmds = shaping_commands(links, lambda d: ips[d])
    assert cmds[0].startswith("tc qdisc replace dev eth0 root handle 1: prio bands 3")
    assert any("netem delay 50ms" in c for c in cmds)
    assert any("netem delay 200ms loss 1.00%" in c for c in cmds)
    assert any("match ip dst 10.0.0.2/32 flowid 1:2" in c for c in cmds)
    assert any("match ip dst 10.0.0.3/32 flowid 1:3" in c for c in cmds)
    assert shaping_commands([], lambda d: ips[d]) == []


def test_match_egress_local_fails_docker_real():
    req = Requirements(egress="blocked")
    assert match(req, PROVIDER_CAPS["local"]).ok is False
    assert match(req, PROVIDER_CAPS["local"]).unmet == [EGRESS_CONTROL]
    docker = match(req, PROVIDER_CAPS["docker"])
    assert docker.ok and docker.fidelity == "real"


def test_link_shaping_is_only_simulated():
    req = Requirements(links=[Link("a", "b", latency_ms=50, loss=0.01)])
    assert match(req, PROVIDER_CAPS["docker"]).fidelity == "simulated"


def test_select_prefers_cheapest_sufficient():
    # egress control is satisfiable by docker (cheaper than microvm) -> docker wins
    assert select_provider(Requirements(egress="blocked")).provider == "docker"
    # no network conditions -> local (cheapest) wins
    assert select_provider(Requirements()).provider == "local"


def test_public_ip_unsatisfiable_by_design():
    # real-host providers are excluded to preserve reproducibility -> nothing offers a public IP
    assert select_provider(Requirements(nodes={"edge": NodeNet(public_ip=True)})) is None
    assert all(PUBLIC_IP not in c.supported for c in PROVIDER_CAPS.values())


def test_strict_run_refuses_unsatisfiable_conditions():
    ch = load_env_challenge(CH_DIR)
    ch.env.requirements = Requirements(egress="blocked")   # local can't block egress
    with pytest.raises(UnsatisfiableEnv):
        run_reference(ch, LocalProvider())                 # strict=True by default


def test_file_server_records_network_provenance():
    ch = load_env_challenge(CH_DIR)
    res = run_reference(ch, LocalProvider())
    net = res["provenance"]["network"]
    assert net["satisfied"] is True and net["fidelity"] == "n/a"   # no conditions required


@pytest.mark.skipif(not DockerComposeProvider().available(), reason="docker daemon not available")
def test_docker_egress_precondition_is_asserted():
    # inject an egress-blocked requirement; docker's internal network really blocks egress, so the
    # precondition must verify as satisfied (capabilities used as a checked precondition)
    ch = load_env_challenge(CH_DIR)
    ch.env.requirements = Requirements(egress="blocked")
    res = run_reference(ch, DockerComposeProvider())
    net = res["provenance"]["network"]
    assert net["satisfied"] and net["fidelity"] == "real"
    egress_check = next(c for c in net["preconditions"] if "egress" in c["name"])
    assert egress_check["ok"] is True
    assert res["passed"] is True
