#!/usr/bin/env python3
"""Generate the long-context "buried routing table" challenge ladder (deterministic, seeded).

A large pasted "codebase" (many decoy modules) is the haystack; one module in the MIDDLE is the
needle. The model must reproduce that module's exact status-code -> service-name table — which only
works if it actually read and retained the far-away module (the lost-in-the-middle failure mode),
not just the start/end of the window. Scoring is deterministic pytest, so it's reproducible.

The ladder scales the haystack size (and the `min_ctx` gate) across difficulty tiers 1-5, so the
axis discriminates from short-context floors up to a frontier rung only 96k+ models attempt. Each
rung has its own seed (distinct needle/tables) and keeps the needle in the middle of the haystack.

Run from the repo root:  python challenges/longcontext/generate.py
Commit the emitted spec.md / meta.toml / tests/ / reference/ (the generator itself is not hashed).
"""
from __future__ import annotations

import random
from pathlib import Path

TABLE_SIZE = 10           # entries in each module's routing table
HERE = Path(__file__).resolve().parent

# The difficulty ladder. Each rung: a distinct seed (different needle), a haystack size (n_modules),
# the served-context window required to attempt it (min_ctx), and the code universe to sample from
# (code_hi must be wide enough that an "absent" code outside every table still exists — large rungs
# would otherwise saturate a narrow range). lc-01 is the original T4 rung, kept byte-identical.
RUNGS = [
    {"id": "lc-01-buried-routes", "n_modules": 66,  "min_ctx": 16384, "difficulty": 4,
     "seed": 1729, "code_hi": 2000},
    {"id": "lc-02-buried-routes", "n_modules": 8,   "min_ctx": 4096,  "difficulty": 1,
     "seed": 2027, "code_hi": 2000},
    {"id": "lc-03-buried-routes", "n_modules": 20,  "min_ctx": 8192,  "difficulty": 2,
     "seed": 4099, "code_hi": 2000},
    {"id": "lc-04-buried-routes", "n_modules": 40,  "min_ctx": 16384, "difficulty": 3,
     "seed": 5051, "code_hi": 2000},
    {"id": "lc-05-buried-routes", "n_modules": 380, "min_ctx": 98304, "difficulty": 5,
     "seed": 6073, "code_hi": 100000},
]

_ADJ = ["amber", "basal", "cobalt", "dusk", "ember", "flint", "garnet", "harbor", "ivory", "jade",
        "kelp", "loom", "mica", "nimbus", "onyx", "pyrite", "quartz", "rill", "slate", "tundra",
        "umber", "verde", "willow", "xenon", "yarrow", "zephyr"]
_NOUN = ["relay", "ledger", "gateway", "broker", "vault", "beacon", "spindle", "anchor", "lattice",
         "cascade", "forge", "harbor", "conduit", "prism", "warden", "cipher", "atlas", "quorum"]


def _svc(rng: random.Random) -> str:
    return f"{rng.choice(_ADJ)}-{rng.choice(_NOUN)}-{rng.randrange(10, 99)}"


def _module(rng: random.Random, idx: int, code_hi: int) -> tuple[str, dict[int, str]]:
    """A plausible-looking decoy module + its (code -> service) table."""
    name = f"svc_{idx:02d}"
    codes = rng.sample(range(1000, code_hi), TABLE_SIZE)
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


def build(rung: dict) -> None:
    n_modules = rung["n_modules"]
    needle_pos = n_modules // 2
    code_hi = rung["code_hi"]
    rng = random.Random(rung["seed"])
    modules, tables = [], []
    for i in range(n_modules):
        src, table = _module(rng, i, code_hi)
        modules.append((f"svc_{i:02d}", src))
        tables.append(table)

    needle_name = f"svc_{needle_pos:02d}"
    needle = tables[needle_pos]

    # a code present in some OTHER module's table but NOT in the needle's -> must resolve to "unknown"
    # (catches a model that grabbed the wrong, more salient, module).
    other_codes = {c for j, t in enumerate(tables) if j != needle_pos for c in t}
    decoy_code = next(c for c in sorted(other_codes) if c not in needle)
    # a code in no table at all
    absent_code = next(c for c in range(1000, code_hi) if c not in needle and c not in other_codes)

    haystack = "\n\n".join(
        f"# ============================ {name}.py ============================\n{src}"
        for name, src in modules)

    spec = f"""# Service-route resolver

Below is a read-only snapshot of our internal `mesh/` package — {n_modules} service-routing
modules. Each module defines its own `ROUTES_NN` table mapping upstream status codes to the
downstream service that handles them.

Your task: implement `solution.py` with a function

```python
def resolve(code: int) -> str:
    ...
```

that reproduces **exactly the routing table defined in module `{needle_name}`** (the
`ROUTES_{needle_pos:02d}` dict). For a status code present in that table, return its service name;
for any other code, return `"unknown"`.

Rules:
- Use the table from `{needle_name}` ONLY. The other modules are decoys with different tables.
- Do NOT import from the snapshot (it is not packaged). Inline the mapping you need.
- Return the literal string `"unknown"` for unrouted codes.

The snapshot follows.

---

{haystack}
"""

    out = HERE / rung["id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "tests").mkdir(exist_ok=True)
    (out / "reference").mkdir(exist_ok=True)
    (out / "spec.md").write_text(spec)

    meta = f'''id            = "{rung["id"]}"
title         = "Service-route resolver (needle in a {n_modules}-module codebase)"
language      = "python"
difficulty    = {rung["difficulty"]}
category      = "long-context"
type          = "long-context"
scoring       = "tests"
solution_file = "solution.py"
timeout       = 60
min_ctx       = {rung["min_ctx"]}

published_at        = "2026-06-30"
published_at_source = "author"
'''
    (out / "meta.toml").write_text(meta)

    ref = "ROUTES = {\n" + "".join(f"    {c}: {n!r},\n" for c, n in needle.items()) + "}\n\n\n"
    ref += 'def resolve(code: int) -> str:\n    return ROUTES.get(code, "unknown")\n'
    (out / "reference" / "solution.py").write_text(ref)

    in_table = "\n".join(f"    assert resolve({c}) == {n!r}" for c, n in needle.items())
    test = f'''from solution import resolve


def test_routes_from_the_needle_module():
    # every code in module {needle_name}'s ROUTES_{needle_pos:02d} table resolves to its service
{in_table}


def test_unrouted_code_is_unknown():
    assert resolve({absent_code}) == "unknown"      # in no module's table


def test_decoy_module_code_is_unknown():
    # {decoy_code} appears in a DIFFERENT module's table but not in {needle_name} -> unknown
    assert resolve({decoy_code}) == "unknown"
'''
    (out / "tests" / "test_resolve.py").write_text(test)

    size = len(spec)
    print(f"wrote {out.name} — diff={rung['difficulty']} spec {size} bytes (~{size // 4} tokens), "
          f"needle={needle_name}, min_ctx={rung['min_ctx']}, decoy={decoy_code}, absent={absent_code}")


def main() -> None:
    for rung in RUNGS:
        build(rung)


if __name__ == "__main__":
    main()
