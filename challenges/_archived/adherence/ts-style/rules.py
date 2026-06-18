"""Deterministic checks for the TypeScript-conventions AGENTS.md."""
import re


def _explicit_return_types(s, r):
    # every `export function name<...>(...)` must be followed by `: <type> {`
    fns = re.findall(r'export\s+function\s+\w+\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(:[^\{]+)?\{', s)
    return bool(fns) and all(rt and rt.strip().startswith(':') for rt in fns)


RULES = [
    {"name": "no_any", "desc": "never use the any type",
     "check": lambda s, r: not re.search(r'(:\s*any\b|<\s*any\b|as\s+any\b|Array<any>)', s)},
    {"name": "const_only", "desc": "const only, no let/var",
     "check": lambda s, r: not re.search(r'\b(let|var)\b', s)},
    {"name": "explicit_return_types", "desc": "exported functions declare return types",
     "check": _explicit_return_types},
    {"name": "no_console", "desc": "no console.*",
     "check": lambda s, r: 'console.' not in s},
]
