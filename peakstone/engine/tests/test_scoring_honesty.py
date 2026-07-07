"""R9-R11 — scoring honesty. The swebench agent can't force green via test-infra files; a test
suite that never ran is a skip, not a 0.0; a declared partition is verified in BOTH directions."""
from types import SimpleNamespace

from peakstone.engine import swebench
from peakstone.engine.env import harness
from peakstone.engine.env.capabilities import Link, Requirements


# --- R9: test-infra tampering is reverted --------------------------------------------------------

class FakeSb:
    """Records exec calls; scripted answers for the two git queries."""

    def __init__(self, changed="", created=""):
        self.calls: list[str] = []
        self._answers = {"git diff --name-only HEAD": changed,
                         "git ls-files --others --exclude-standard": created}

    def exec(self, cmd, **kw):
        self.calls.append(cmd)
        return SimpleNamespace(stdout=self._answers.get(cmd, ""), stderr="", rc=0)


def test_infra_edits_reverted_and_created_files_removed():
    sb = FakeSb(changed="src/real_fix.py\nconftest.py\nsub/pkg/conftest.py\nsetup.cfg\n",
                created="src/new_module.py\ntests/conftest.py\nsitecustomize.py\n")
    log: list = []
    inst = {"test_patch": ""}
    swebench._revert_test_tampering(sb, inst, log)
    reverts = [c for c in sb.calls if c.startswith("git checkout")]
    removes = [c for c in sb.calls if c.startswith("rm -f")]
    # every infra file (any depth) reverted/removed; the model's real source edits untouched
    assert any("conftest.py" in c and "sub/pkg" in c for c in reverts)
    assert any("setup.cfg" in c for c in reverts)
    assert {"rm -f tests/conftest.py", "rm -f sitecustomize.py"} <= set(removes)
    assert not any("real_fix.py" in c or "new_module.py" in c for c in reverts + removes)
    assert len(log) == 5   # 3 reverted edits + 2 removed creations, all documented


def test_graded_test_files_still_reverted():
    patch = ("diff --git a/tests/test_bug.py b/tests/test_bug.py\n"
             "--- a/tests/test_bug.py\n+++ b/tests/test_bug.py\n@@ -1 +1 @@\n-x\n+y\n")
    sb = FakeSb()
    swebench._revert_test_tampering(sb, {"test_patch": patch}, [])
    assert any("git checkout" in c and "tests/test_bug.py" in c for c in sb.calls)


# --- R10: environment failures are unscored, never 0.0 -------------------------------------------

def test_setup_failure_is_unscored():
    res = swebench._fail("repo setup failed", [], "img", "d", ["t::a"], 0.0, unscored=True)
    assert res["unscored"] is True and res["final"] == 0.0     # caller must skip, not append
    res = swebench._fail("patch did not apply", [], "img", "d", ["t::a"], 0.0)
    assert res["unscored"] is False                            # the model's fault → scored


# --- R11: partitions are probed in BOTH directions ------------------------------------------------

class FakeNode:
    def __init__(self, env, name):
        self.env, self.name = env, name

    def run(self, probe, timeout=8):
        # the probe targets a host named after the destination node (see FakeEnv.address_of)
        dst = probe.split("create_connection(('")[1].split("'")[0]
        reached = (self.name, dst) in self.env.reachable
        return SimpleNamespace(rc=0 if reached else 1)


class FakeEnv:
    """Two serving nodes; `reachable` lists (src, dst) pairs that can still connect."""

    def __init__(self, reachable):
        self.nodes = {"a": None, "b": None}
        self.reachable = set(reachable)

    def address_of(self, name):
        return name, 9000

    def node(self, name):
        return FakeNode(self, name)


def _blocked_req():
    return Requirements(links=[Link(src="a", dst="b", firewall="blocked")])


def test_full_partition_passes_both_probes():
    checks = harness.check_preconditions(FakeEnv(reachable=[]), _blocked_req())
    names = {c["name"]: c["ok"] for c in checks}
    assert names == {"link a->b blocked": True, "link b->a blocked": True}


def test_half_open_partition_is_caught():
    # a->b dropped, but b can still reach a: the OLD one-directional probe passed this
    checks = harness.check_preconditions(FakeEnv(reachable=[("b", "a")]), _blocked_req())
    names = {c["name"]: c["ok"] for c in checks}
    assert names["link a->b blocked"] is True
    assert names["link b->a blocked"] is False      # the leak is now a failed precondition
