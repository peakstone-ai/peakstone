ROUTES = {
    1936: 'umber-anchor-97',
    1610: 'cobalt-cascade-23',
    1686: 'cobalt-anchor-27',
    1786: 'dusk-spindle-42',
    1869: 'amber-gateway-79',
    1748: 'jade-quorum-60',
    1553: 'umber-prism-50',
    1818: 'ivory-atlas-63',
    1921: 'quartz-spindle-54',
    1516: 'cobalt-spindle-28',
}


def resolve(code: int) -> str:
    return ROUTES.get(code, "unknown")
