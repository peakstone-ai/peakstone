"""Deterministic checks for the Python-conventions AGENTS.md. Each check(solution, response)."""
import re


def _defs(sol):
    # (name, params, ret) ; ret is '->...' or '' if absent
    return re.findall(r'def\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*(->[^:]+)?:', sol, re.DOTALL)


def _params_typed(params):
    for p in (x.strip() for x in params.split(',')):
        if not p:
            continue
        base = p.split('=')[0].strip()
        if base in ('self', 'cls') or base.startswith('*'):
            continue
        if ':' not in base:
            return False
    return True


def _type_hints(s, r):
    ds = _defs(s)
    return bool(ds) and all(d[2].strip().startswith('->') for d in ds) and \
        all(_params_typed(d[1]) for d in ds)


def _docstrings(s, r):
    n_def = len(re.findall(r'\bdef\s', s))
    n_doc = len(re.findall(
        r'def\s+[A-Za-z_]\w*\s*\(.*?\)\s*(?:->[^:]+)?:[ \t]*\n[ \t]+(?:"""|\'\'\'|"|\')',
        s, re.DOTALL))
    return n_def > 0 and n_doc == n_def


RULES = [
    {"name": "type_hints", "desc": "every function fully type-hinted", "check": _type_hints},
    {"name": "docstrings", "desc": "every function has a docstring", "check": _docstrings},
    {"name": "no_print", "desc": "no print()", "check": lambda s, r: 'print(' not in s},
    {"name": "no_pct_or_format", "desc": "f-strings only",
     "check": lambda s, r: '.format(' not in s and not re.search(r"""['"][^'"\n]*%[sdrfg]""", s)},
    {"name": "snake_case", "desc": "snake_case function names",
     "check": lambda s, r: all(re.fullmatch(r'[a-z_][a-z0-9_]*', d[0]) for d in _defs(s))},
    {"name": "stdlib_only", "desc": "standard library only",
     "check": lambda s, r: not re.search(
         r'^\s*(?:import|from)\s+(numpy|pandas|requests|httpx|scipy|sklearn|torch|pydantic|networkx|aiohttp)\b',
         s, re.M)},
]
