from solution import resolve


def test_routes_from_the_needle_module():
    # every code in module svc_20's ROUTES_20 table resolves to its service
    assert resolve(1043) == 'slate-conduit-35'
    assert resolve(1985) == 'slate-atlas-86'
    assert resolve(1452) == 'yarrow-broker-77'
    assert resolve(1216) == 'umber-relay-15'
    assert resolve(1306) == 'umber-vault-80'
    assert resolve(1223) == 'garnet-anchor-37'
    assert resolve(1970) == 'slate-ledger-28'
    assert resolve(1121) == 'yarrow-harbor-44'
    assert resolve(1655) == 'flint-prism-85'
    assert resolve(1006) == 'ember-cipher-73'


def test_unrouted_code_is_unknown():
    assert resolve(1001) == "unknown"      # in no module's table


def test_decoy_module_code_is_unknown():
    # 1000 appears in a DIFFERENT module's table but not in svc_20 -> unknown
    assert resolve(1000) == "unknown"
