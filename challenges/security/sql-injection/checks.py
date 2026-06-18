import re
RULES = [
    {"name": "parameterized", "desc": "uses a ? placeholder with bound params",
     "check": lambda s, r: bool(re.search(r'execute\(\s*["\'][^"\']*\?', s)) and bool(re.search(r'execute\([^)]*,\s*[\(\[]', s))},
    {"name": "no_string_interpolation", "desc": "no f-string/%/+/.format into the query",
     "check": lambda s, r: not re.search(r'execute\(\s*f["\']', s) and '.format(' not in s
                           and not re.search(r'execute\([^)]*%[^)]*\)', s)
                           and not re.search(r'execute\([^)]*\+', s)},
]
