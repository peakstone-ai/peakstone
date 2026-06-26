from solution import resolve


def test_routes_from_the_needle_module():
    # every code in module svc_33's ROUTES_33 table resolves to its service
    assert resolve(1936) == 'umber-anchor-97'
    assert resolve(1610) == 'cobalt-cascade-23'
    assert resolve(1686) == 'cobalt-anchor-27'
    assert resolve(1786) == 'dusk-spindle-42'
    assert resolve(1869) == 'amber-gateway-79'
    assert resolve(1748) == 'jade-quorum-60'
    assert resolve(1553) == 'umber-prism-50'
    assert resolve(1818) == 'ivory-atlas-63'
    assert resolve(1921) == 'quartz-spindle-54'
    assert resolve(1516) == 'cobalt-spindle-28'


def test_unrouted_code_is_unknown():
    assert resolve(1000) == "unknown"      # in no module's table


def test_decoy_module_code_is_unknown():
    # 1001 appears in a DIFFERENT module's table but not in svc_33 -> unknown
    assert resolve(1001) == "unknown"
