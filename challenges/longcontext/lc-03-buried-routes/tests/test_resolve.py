from solution import resolve


def test_routes_from_the_needle_module():
    # every code in module svc_10's ROUTES_10 table resolves to its service
    assert resolve(1816) == 'basal-prism-81'
    assert resolve(1120) == 'ivory-lattice-41'
    assert resolve(1471) == 'amber-forge-56'
    assert resolve(1407) == 'willow-cascade-51'
    assert resolve(1712) == 'yarrow-cipher-95'
    assert resolve(1869) == 'xenon-cascade-45'
    assert resolve(1730) == 'jade-warden-41'
    assert resolve(1779) == 'kelp-conduit-19'
    assert resolve(1235) == 'zephyr-atlas-11'
    assert resolve(1135) == 'garnet-warden-15'


def test_unrouted_code_is_unknown():
    assert resolve(1000) == "unknown"      # in no module's table


def test_decoy_module_code_is_unknown():
    # 1002 appears in a DIFFERENT module's table but not in svc_10 -> unknown
    assert resolve(1002) == "unknown"
