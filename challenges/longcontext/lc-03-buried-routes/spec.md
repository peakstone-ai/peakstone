# Service-route resolver

Below is a read-only snapshot of our internal `mesh/` package — 20 service-routing
modules. Each module defines its own `ROUTES_NN` table mapping upstream status codes to the
downstream service that handles them.

Your task: implement `solution.py` with a function

```python
def resolve(code: int) -> str:
    ...
```

that reproduces **exactly the routing table defined in module `svc_10`** (the
`ROUTES_10` dict). For a status code present in that table, return its service name;
for any other code, return `"unknown"`.

Rules:
- Use the table from `svc_10` ONLY. The other modules are decoys with different tables.
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
    1385: 'dusk-vault-70',
    1025: 'onyx-beacon-82',
    1369: 'loom-gateway-15',
    1395: 'tundra-forge-68',
    1689: 'quartz-warden-71',
    1736: 'cobalt-ledger-43',
    1221: 'zephyr-ledger-88',
    1420: 'flint-spindle-33',
    1678: 'cobalt-spindle-42',
    1989: 'loom-harbor-35',
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
    1719: 'loom-ledger-48',
    1897: 'pyrite-forge-97',
    1376: 'quartz-forge-49',
    1807: 'xenon-prism-41',
    1552: 'quartz-prism-19',
    1456: 'nimbus-cipher-15',
    1931: 'garnet-relay-49',
    1856: 'nimbus-harbor-26',
    1877: 'yarrow-anchor-58',
    1461: 'flint-beacon-91',
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
    1765: 'slate-broker-58',
    1470: 'nimbus-cascade-52',
    1319: 'cobalt-vault-10',
    1782: 'quartz-broker-79',
    1546: 'umber-lattice-88',
    1837: 'amber-relay-37',
    1668: 'pyrite-conduit-61',
    1107: 'pyrite-relay-73',
    1916: 'rill-harbor-72',
    1190: 'willow-gateway-93',
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
    1382: 'dusk-cascade-30',
    1287: 'dusk-relay-11',
    1945: 'flint-prism-17',
    1455: 'loom-beacon-79',
    1829: 'mica-harbor-90',
    1749: 'ember-gateway-86',
    1056: 'xenon-ledger-17',
    1592: 'flint-lattice-52',
    1164: 'yarrow-beacon-70',
    1116: 'tundra-forge-91',
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
    1444: 'slate-relay-47',
    1270: 'amber-relay-91',
    1563: 'verde-quorum-34',
    1042: 'zephyr-relay-97',
    1172: 'verde-relay-46',
    1476: 'jade-cipher-50',
    1332: 'pyrite-spindle-37',
    1712: 'kelp-forge-58',
    1243: 'tundra-beacon-10',
    1037: 'loom-relay-11',
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
    1751: 'ember-warden-89',
    1953: 'jade-warden-80',
    1326: 'willow-gateway-89',
    1391: 'cobalt-quorum-60',
    1185: 'zephyr-ledger-64',
    1914: 'basal-quorum-91',
    1674: 'kelp-warden-24',
    1393: 'umber-quorum-84',
    1487: 'amber-relay-81',
    1230: 'quartz-anchor-96',
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
    1573: 'rill-lattice-60',
    1558: 'mica-anchor-91',
    1872: 'ember-lattice-25',
    1847: 'harbor-beacon-57',
    1570: 'harbor-spindle-73',
    1057: 'loom-atlas-31',
    1126: 'dusk-harbor-28',
    1152: 'umber-ledger-62',
    1559: 'ivory-relay-54',
    1185: 'onyx-spindle-26',
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
    1224: 'xenon-conduit-48',
    1879: 'mica-harbor-28',
    1672: 'cobalt-lattice-16',
    1148: 'quartz-forge-58',
    1342: 'harbor-vault-48',
    1326: 'dusk-warden-20',
    1294: 'tundra-warden-49',
    1207: 'basal-atlas-22',
    1087: 'jade-spindle-12',
    1075: 'slate-anchor-78',
}


def resolve_07(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_07.get(code, "unknown")


def is_routed_07(code: int) -> bool:
    return code in ROUTES_07


# ============================ svc_08.py ============================
"""Service routing for the svc_08 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_08 = {
    1424: 'dusk-gateway-41',
    1266: 'cobalt-ledger-34',
    1310: 'tundra-atlas-77',
    1397: 'ivory-cascade-71',
    1047: 'basal-conduit-78',
    1769: 'flint-harbor-98',
    1633: 'harbor-gateway-64',
    1463: 'quartz-conduit-64',
    1322: 'loom-harbor-94',
    1707: 'umber-conduit-72',
}


def resolve_08(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_08.get(code, "unknown")


def is_routed_08(code: int) -> bool:
    return code in ROUTES_08


# ============================ svc_09.py ============================
"""Service routing for the svc_09 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_09 = {
    1274: 'yarrow-relay-40',
    1121: 'tundra-lattice-97',
    1494: 'nimbus-prism-90',
    1046: 'ivory-gateway-67',
    1843: 'ivory-broker-33',
    1657: 'harbor-prism-30',
    1360: 'mica-ledger-32',
    1914: 'dusk-warden-68',
    1331: 'onyx-spindle-98',
    1440: 'verde-broker-92',
}


def resolve_09(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_09.get(code, "unknown")


def is_routed_09(code: int) -> bool:
    return code in ROUTES_09


# ============================ svc_10.py ============================
"""Service routing for the svc_10 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_10 = {
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


def resolve_10(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_10.get(code, "unknown")


def is_routed_10(code: int) -> bool:
    return code in ROUTES_10


# ============================ svc_11.py ============================
"""Service routing for the svc_11 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_11 = {
    1366: 'nimbus-cipher-54',
    1369: 'ember-beacon-50',
    1598: 'quartz-broker-88',
    1335: 'pyrite-quorum-81',
    1377: 'kelp-spindle-56',
    1459: 'nimbus-spindle-31',
    1663: 'quartz-forge-16',
    1477: 'kelp-conduit-75',
    1080: 'ivory-prism-31',
    1314: 'basal-harbor-75',
}


def resolve_11(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_11.get(code, "unknown")


def is_routed_11(code: int) -> bool:
    return code in ROUTES_11


# ============================ svc_12.py ============================
"""Service routing for the svc_12 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_12 = {
    1586: 'yarrow-harbor-59',
    1833: 'quartz-vault-42',
    1720: 'umber-prism-67',
    1971: 'basal-warden-34',
    1289: 'willow-spindle-34',
    1061: 'rill-relay-59',
    1947: 'garnet-quorum-38',
    1104: 'quartz-anchor-70',
    1283: 'zephyr-anchor-33',
    1077: 'amber-conduit-20',
}


def resolve_12(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_12.get(code, "unknown")


def is_routed_12(code: int) -> bool:
    return code in ROUTES_12


# ============================ svc_13.py ============================
"""Service routing for the svc_13 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_13 = {
    1386: 'xenon-forge-50',
    1771: 'zephyr-cipher-83',
    1343: 'tundra-quorum-35',
    1852: 'zephyr-anchor-90',
    1524: 'slate-spindle-63',
    1281: 'dusk-harbor-50',
    1221: 'tundra-atlas-97',
    1486: 'amber-vault-30',
    1890: 'jade-broker-10',
    1736: 'onyx-anchor-49',
}


def resolve_13(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_13.get(code, "unknown")


def is_routed_13(code: int) -> bool:
    return code in ROUTES_13


# ============================ svc_14.py ============================
"""Service routing for the svc_14 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_14 = {
    1777: 'willow-conduit-57',
    1170: 'onyx-forge-28',
    1728: 'dusk-cipher-16',
    1092: 'tundra-harbor-69',
    1785: 'yarrow-lattice-25',
    1554: 'quartz-ledger-39',
    1105: 'rill-broker-48',
    1738: 'quartz-beacon-13',
    1731: 'flint-atlas-27',
    1533: 'willow-anchor-46',
}


def resolve_14(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_14.get(code, "unknown")


def is_routed_14(code: int) -> bool:
    return code in ROUTES_14


# ============================ svc_15.py ============================
"""Service routing for the svc_15 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_15 = {
    1990: 'willow-beacon-13',
    1866: 'tundra-lattice-82',
    1566: 'mica-gateway-63',
    1530: 'kelp-relay-47',
    1804: 'willow-vault-85',
    1181: 'slate-lattice-65',
    1336: 'loom-anchor-96',
    1366: 'flint-forge-84',
    1417: 'dusk-ledger-70',
    1913: 'ember-vault-66',
}


def resolve_15(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_15.get(code, "unknown")


def is_routed_15(code: int) -> bool:
    return code in ROUTES_15


# ============================ svc_16.py ============================
"""Service routing for the svc_16 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_16 = {
    1358: 'flint-cipher-36',
    1209: 'pyrite-broker-22',
    1740: 'xenon-prism-96',
    1840: 'onyx-cascade-88',
    1875: 'dusk-harbor-44',
    1434: 'umber-prism-24',
    1877: 'umber-beacon-21',
    1783: 'rill-harbor-25',
    1081: 'amber-harbor-37',
    1927: 'zephyr-spindle-40',
}


def resolve_16(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_16.get(code, "unknown")


def is_routed_16(code: int) -> bool:
    return code in ROUTES_16


# ============================ svc_17.py ============================
"""Service routing for the svc_17 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_17 = {
    1130: 'quartz-forge-56',
    1843: 'willow-cipher-41',
    1587: 'ember-quorum-80',
    1869: 'amber-cipher-77',
    1955: 'yarrow-spindle-66',
    1636: 'garnet-harbor-75',
    1960: 'rill-lattice-24',
    1120: 'ivory-relay-98',
    1912: 'zephyr-conduit-98',
    1492: 'nimbus-quorum-78',
}


def resolve_17(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_17.get(code, "unknown")


def is_routed_17(code: int) -> bool:
    return code in ROUTES_17


# ============================ svc_18.py ============================
"""Service routing for the svc_18 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_18 = {
    1405: 'amber-conduit-47',
    1881: 'dusk-spindle-57',
    1926: 'basal-anchor-98',
    1670: 'jade-broker-82',
    1002: 'dusk-relay-91',
    1992: 'nimbus-prism-19',
    1173: 'onyx-warden-71',
    1977: 'nimbus-vault-49',
    1327: 'xenon-beacon-72',
    1898: 'basal-vault-52',
}


def resolve_18(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_18.get(code, "unknown")


def is_routed_18(code: int) -> bool:
    return code in ROUTES_18


# ============================ svc_19.py ============================
"""Service routing for the svc_19 edge cluster.

Auto-generated from the service mesh manifest. Maps upstream status codes to the
downstream service that should handle the retry/escalation for that code.
"""

ROUTES_19 = {
    1162: 'slate-vault-94',
    1786: 'slate-atlas-49',
    1629: 'onyx-cipher-89',
    1594: 'amber-cipher-67',
    1875: 'flint-anchor-73',
    1100: 'flint-harbor-18',
    1180: 'basal-forge-47',
    1057: 'slate-conduit-61',
    1973: 'loom-quorum-50',
    1075: 'kelp-vault-48',
}


def resolve_19(code: int) -> str:
    """Return the handling service for a status code, or "unknown" if unrouted."""
    return ROUTES_19.get(code, "unknown")


def is_routed_19(code: int) -> bool:
    return code in ROUTES_19

