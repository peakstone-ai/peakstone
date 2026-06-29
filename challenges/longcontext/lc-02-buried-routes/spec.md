# Service-route resolver

Below is a read-only snapshot of our internal `mesh/` package — 8 service-routing
modules. Each module defines its own `ROUTES_NN` table mapping upstream status codes to the
downstream service that handles them.

Your task: implement `solution.py` with a function

```python
def resolve(code: int) -> str:
    ...
```

that reproduces **exactly the routing table defined in module `svc_04`** (the
`ROUTES_04` dict). For a status code present in that table, return its service name;
for any other code, return `"unknown"`.

Rules:
- Use the table from `svc_04` ONLY. The other modules are decoys with different tables.
- Do NOT import from the snapshot (it is not packaged). Inline the mapping you need.
- Return the literal string `"unknown"` for unrouted codes.

The snapshot follows.

---

# ============================ svc_00.py ============================
"""Service routing for the svc_00 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_00 = {
    1110: 'zephyr-beacon-61',
    1949: 'flint-harbor-86',
    1475: 'flint-lattice-46',
    1081: 'verde-gateway-91',
    1013: 'verde-forge-48',
    1670: 'cobalt-lattice-93',
    1330: 'ivory-prism-74',
    1811: 'harbor-beacon-53',
    1415: 'loom-anchor-60',
    1640: 'onyx-conduit-30',
}


def resolve_00(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_00.get(code, "unknown")


def is_routed_00(code: int) -> bool:
    return code in ROUTES_00


# ============================ svc_01.py ============================
"""Service routing for the svc_01 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_01 = {
    1887: 'dusk-spindle-17',
    1810: 'kelp-cipher-43',
    1479: 'quartz-broker-45',
    1382: 'yarrow-prism-59',
    1936: 'slate-gateway-32',
    1754: 'ivory-gateway-20',
    1807: 'zephyr-quorum-74',
    1322: 'nimbus-gateway-72',
    1628: 'harbor-spindle-14',
    1862: 'dusk-cascade-85',
}


def resolve_01(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_01.get(code, "unknown")


def is_routed_01(code: int) -> bool:
    return code in ROUTES_01


# ============================ svc_02.py ============================
"""Service routing for the svc_02 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_02 = {
    1645: 'tundra-vault-53',
    1775: 'onyx-relay-26',
    1519: 'amber-relay-90',
    1679: 'kelp-harbor-75',
    1092: 'jade-atlas-59',
    1550: 'pyrite-warden-36',
    1028: 'mica-warden-33',
    1599: 'pyrite-lattice-40',
    1641: 'tundra-relay-71',
    1123: 'willow-lattice-91',
}


def resolve_02(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_02.get(code, "unknown")


def is_routed_02(code: int) -> bool:
    return code in ROUTES_02


# ============================ svc_03.py ============================
"""Service routing for the svc_03 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_03 = {
    1682: 'dusk-gateway-49',
    1602: 'pyrite-prism-27',
    1571: 'verde-lattice-66',
    1156: 'xenon-vault-42',
    1219: 'willow-prism-44',
    1370: 'loom-anchor-83',
    1764: 'quartz-prism-93',
    1676: 'quartz-relay-35',
    1677: 'onyx-vault-93',
    1236: 'jade-beacon-29',
}


def resolve_03(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_03.get(code, "unknown")


def is_routed_03(code: int) -> bool:
    return code in ROUTES_03


# ============================ svc_04.py ============================
"""Service routing for the svc_04 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_04 = {
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


def resolve_04(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_04.get(code, "unknown")


def is_routed_04(code: int) -> bool:
    return code in ROUTES_04


# ============================ svc_05.py ============================
"""Service routing for the svc_05 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_05 = {
    1257: 'umber-spindle-28',
    1899: 'cobalt-beacon-93',
    1069: 'kelp-prism-58',
    1837: 'willow-vault-16',
    1203: 'flint-relay-83',
    1938: 'onyx-atlas-52',
    1395: 'garnet-beacon-46',
    1543: 'dusk-spindle-69',
    1576: 'garnet-anchor-19',
    1320: 'kelp-spindle-22',
}


def resolve_05(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_05.get(code, "unknown")


def is_routed_05(code: int) -> bool:
    return code in ROUTES_05


# ============================ svc_06.py ============================
"""Service routing for the svc_06 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_06 = {
    1188: 'mica-anchor-74',
    1485: 'umber-quorum-17',
    1581: 'onyx-vault-31',
    1149: 'onyx-cipher-34',
    1801: 'umber-gateway-37',
    1732: 'willow-cascade-76',
    1532: 'cobalt-anchor-36',
    1131: 'slate-warden-12',
    1508: 'flint-conduit-84',
    1079: 'slate-cascade-67',
}


def resolve_06(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_06.get(code, "unknown")


def is_routed_06(code: int) -> bool:
    return code in ROUTES_06


# ============================ svc_07.py ============================
"""Service routing for the svc_07 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_07 = {
    1773: 'slate-spindle-43',
    1927: 'cobalt-lattice-15',
    1051: 'nimbus-vault-87',
    1715: 'ivory-lattice-62',
    1198: 'umber-cipher-47',
    1906: 'ember-beacon-28',
    1397: 'verde-relay-17',
    1657: 'basal-beacon-91',
    1164: 'rill-atlas-93',
    1580: 'dusk-atlas-29',
}


def resolve_07(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_07.get(code, "unknown")


def is_routed_07(code: int) -> bool:
    return code in ROUTES_07

