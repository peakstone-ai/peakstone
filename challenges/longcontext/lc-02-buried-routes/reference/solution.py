ROUTES = {
    1402: 'mica-lattice-97',
    1604: 'jade-lattice-34',
    1310: 'dusk-broker-38',
    1210: 'ivory-prism-21',
    1263: 'amber-warden-15',
    1366: 'yarrow-vault-11',
    1880: 'mica-spindle-49',
    1597: 'slate-lattice-78',
    1198: 'mica-broker-93',
    1626: 'cobalt-quorum-63',
}


def resolve(code: int) -> str:
    return ROUTES.get(code, "unknown")
