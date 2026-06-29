from solution import resolve


def test_routes_from_the_needle_module():
    # every code in module svc_04's ROUTES_04 table resolves to its service
    assert resolve(1402) == 'mica-lattice-97'
    assert resolve(1604) == 'jade-lattice-34'
    assert resolve(1310) == 'dusk-broker-38'
    assert resolve(1210) == 'ivory-prism-21'
    assert resolve(1263) == 'amber-warden-15'
    assert resolve(1366) == 'yarrow-vault-11'
    assert resolve(1880) == 'mica-spindle-49'
    assert resolve(1597) == 'slate-lattice-78'
    assert resolve(1198) == 'mica-broker-93'
    assert resolve(1626) == 'cobalt-quorum-63'


def test_unrouted_code_is_unknown():
    assert resolve(1000) == "unknown"      # in no module's table


def test_decoy_module_code_is_unknown():
    # 1013 appears in a DIFFERENT module's table but not in svc_04 -> unknown
    assert resolve(1013) == "unknown"
