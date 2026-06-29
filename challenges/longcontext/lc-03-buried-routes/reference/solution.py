ROUTES = {
    1816: 'basal-prism-81',
    1120: 'ivory-lattice-41',
    1471: 'amber-forge-56',
    1407: 'willow-cascade-51',
    1712: 'yarrow-cipher-95',
    1869: 'xenon-cascade-45',
    1730: 'jade-warden-41',
    1779: 'kelp-conduit-19',
    1235: 'zephyr-atlas-11',
    1135: 'garnet-warden-15',
}


def resolve(code: int) -> str:
    return ROUTES.get(code, "unknown")
