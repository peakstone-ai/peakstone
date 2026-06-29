ROUTES = {
    91894: 'jade-forge-57',
    79981: 'slate-relay-53',
    77875: 'kelp-beacon-18',
    73048: 'tundra-cascade-51',
    54517: 'basal-quorum-74',
    51408: 'loom-lattice-81',
    17389: 'slate-cascade-62',
    48294: 'flint-atlas-61',
    84507: 'rill-beacon-84',
    96353: 'amber-quorum-50',
}


def resolve(code: int) -> str:
    return ROUTES.get(code, "unknown")
