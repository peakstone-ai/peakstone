import re
RULES = [
    {"name": "no_eval_exec", "desc": "no eval()/exec()",
     "check": lambda s, r: not re.search(r'\beval\s*\(', s) and not re.search(r'\bexec\s*\(', s)},
    {"name": "safe_parse", "desc": "uses json.loads or ast.literal_eval",
     "check": lambda s, r: bool(re.search(r'json\.loads|ast\.literal_eval', s))},
]
