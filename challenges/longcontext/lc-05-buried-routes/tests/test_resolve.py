from solution import resolve


def test_routes_from_the_needle_module():
    # every code in module svc_190's ROUTES_190 table resolves to its service
    assert resolve(91894) == 'jade-forge-57'
    assert resolve(79981) == 'slate-relay-53'
    assert resolve(77875) == 'kelp-beacon-18'
    assert resolve(73048) == 'tundra-cascade-51'
    assert resolve(54517) == 'basal-quorum-74'
    assert resolve(51408) == 'loom-lattice-81'
    assert resolve(17389) == 'slate-cascade-62'
    assert resolve(48294) == 'flint-atlas-61'
    assert resolve(84507) == 'rill-beacon-84'
    assert resolve(96353) == 'amber-quorum-50'


def test_unrouted_code_is_unknown():
    assert resolve(1000) == "unknown"      # in no module's table


def test_decoy_module_code_is_unknown():
    # 1041 appears in a DIFFERENT module's table but not in svc_190 -> unknown
    assert resolve(1041) == "unknown"
