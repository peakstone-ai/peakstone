#!/usr/bin/env python3
"""Generate the long-context "buried routing table" challenge (deterministic, seeded).

A large pasted "codebase" (many decoy modules) is the haystack; one module in the MIDDLE is the
needle. The model must reproduce that module's exact status-code -> service-name table — which only
works if it actually read and retained the far-away module (the lost-in-the-middle failure mode),
not just the start/end of the window. Scoring is deterministic pytest, so it's reproducible.

Run from the repo root:  python challenges/longcontext/generate.py
Commit the emitted spec.md / meta.toml / tests/ / reference/ (the generator itself is not hashed).
"""
from __future__ import annotations

import random
from pathlib import Path

SEED = 1729
N_MODULES = 66            # decoy modules surrounding the needle (~45 KB haystack ≈ ~11k tokens)
NEEDLE_POS = 33           # 0-based index of the needle module (middle -> lost-in-the-middle)
TABLE_SIZE = 10           # entries in each module's routing table
MIN_CTX = 16384           # served window required to attempt (smaller windows are gated out)
OUT = Path(__file__).resolve().parent / "lc-01-buried-routes"

_ADJ = ["amber", "basal", "cobalt", "dusk", "ember", "flint", "garnet", "harbor", "ivory", "jade",
        "kelp", "loom", "mica", "nimbus", "onyx", "pyrite", "quartz", "rill", "slate", "tundra",
        "umber", "verde", "willow", "xenon", "yarrow", "zephyr"]
_NOUN = ["relay", "ledger", "gateway", "broker", "vault", "beacon", "spindle", "anchor", "lattice",
         "cascade", "forge", "harbor", "conduit", "prism", "warden", "cipher", "atlas", "quorum"]


def _svc(rng: random.Random) -> str:
    return f"{rng.choice(_ADJ)}-{rng.choice(_NOUN)}-{rng.randrange(10, 99)}"


def _module(rng: random.Random, idx: int) -> tuple[str, dict[int, str]]:
    """A plausible-looking decoy module + its (code -> service) table."""
    name = f"svc_{idx:02d}"
    codes = rng.sample(range(1000, 2000), TABLE_SIZE)
    table = {c: _svc(rng) for c in codes}
    lines = [
        f'"""Service routing for the {name} edge cluster.',
        "",
        "Auto-generated from the service mesh manifest. Maps upstream status codes to the",
        "downstream service that should handle the retry/escalation for that code.",
        '"""',
        "",
        f"ROUTES_{idx:02d} = {{",
    ]
    lines += [f"    {c}: {n!r}," for c, n in table.items()]
    lines += [
        "}",
        "",
        "",
        f"def resolve_{idx:02d}(code: int) -> str:",
        '    """Return the handling service for a status code, or "unknown" if unrouted."""',
        f"    return ROUTES_{idx:02d}.get(code, \"unknown\")",
        "",
        "",
        f"def is_routed_{idx:02d}(code: int) -> bool:",
        f"    return code in ROUTES_{idx:02d}",
        "",
    ]
    return "\n".join(lines), table


def main() -> None:
    rng = random.Random(SEED)
    modules, tables = [], []
    for i in range(N_MODULES):
        src, table = _module(rng, i)
        modules.append((f"svc_{i:02d}", src))
        tables.append(table)

    needle_name = f"svc_{NEEDLE_POS:02d}"
    needle = tables[NEEDLE_POS]

    # a code present in some OTHER module's table but NOT in the needle's -> must resolve to "unknown"
    # (catches a model that grabbed the wrong, more salient, module).
    other_codes = {c for j, t in enumerate(tables) if j != NEEDLE_POS for c in t}
    decoy_code = next(c for c in sorted(other_codes) if c not in needle)
    # a code in no table at all
    absent_code = next(c for c in range(1000, 2000) if c not in needle and c not in other_codes)

    haystack = "\n\n".join(
        f"# ============================ {name}.py ============================\n{src}"
        for name, src in modules)

    spec = f"""# Service-route resolver

Below is a read-only snapshot of our internal `mesh/` package — {N_MODULES} service-routing
modules. Each module defines its own `ROUTES_NN` table mapping upstream status codes to the
downstream service that handles them.

Your task: implement `solution.py` with a function

```python
def resolve(code: int) -> str:
    ...
```

that reproduces **exactly the routing table defined in module `{needle_name}`** (the
`ROUTES_{NEEDLE_POS:02d}` dict). For a status code present in that table, return its service name;
for any other code, return `"unknown"`.

Rules:
- Use the table from `{needle_name}` ONLY. The other modules are decoys with different tables.
- Do NOT import from the snapshot (it is not packaged). Inline the mapping you need.
- Return the literal string `"unknown"` for unrouted codes.

The snapshot follows.

---

{haystack}
"""

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tests").mkdir(exist_ok=True)
    (OUT / "reference").mkdir(exist_ok=True)
    (OUT / "spec.md").write_text(spec)

    meta = f'''id            = "lc-01-buried-routes"
title         = "Service-route resolver (needle in a {N_MODULES}-module codebase)"
language      = "python"
difficulty    = 4
category      = "long-context"
type          = "long-context"
scoring       = "tests"
solution_file = "solution.py"
timeout       = 60
min_ctx       = {MIN_CTX}

published_at        = "2026-06-30"
published_at_source = "author"
'''
    (OUT / "meta.toml").write_text(meta)

    ref = "ROUTES = {\n" + "".join(f"    {c}: {n!r},\n" for c, n in needle.items()) + "}\n\n\n"
    ref += 'def resolve(code: int) -> str:\n    return ROUTES.get(code, "unknown")\n'
    (OUT / "reference" / "solution.py").write_text(ref)

    in_table = "\n".join(f"    assert resolve({c}) == {n!r}" for c, n in needle.items())
    test = f'''from solution import resolve


def test_routes_from_the_needle_module():
    # every code in module {needle_name}'s ROUTES_{NEEDLE_POS:02d} table resolves to its service
{in_table}


def test_unrouted_code_is_unknown():
    assert resolve({absent_code}) == "unknown"      # in no module's table


def test_decoy_module_code_is_unknown():
    # {decoy_code} appears in a DIFFERENT module's table but not in {needle_name} -> unknown
    assert resolve({decoy_code}) == "unknown"
'''
    (OUT / "tests" / "test_resolve.py").write_text(test)

    size = len(spec)
    print(f"wrote {OUT} — spec {size} bytes (~{size // 4} tokens), needle={needle_name}, "
          f"min_ctx={MIN_CTX}, decoy_code={decoy_code}, absent_code={absent_code}")


if __name__ == "__main__":
    main()
