ROUTES = {
    1043: 'slate-conduit-35',
    1985: 'slate-atlas-86',
    1452: 'yarrow-broker-77',
    1216: 'umber-relay-15',
    1306: 'umber-vault-80',
    1223: 'garnet-anchor-37',
    1970: 'slate-ledger-28',
    1121: 'yarrow-harbor-44',
    1655: 'flint-prism-85',
    1006: 'ember-cipher-73',
}


def resolve(code: int) -> str:
    return ROUTES.get(code, "unknown")
