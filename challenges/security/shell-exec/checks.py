import re
RULES = [
    {"name": "no_shell", "desc": "no shell=True / os.system / os.popen",
     "check": lambda s, r: 'shell=True' not in s and not re.search(r'os\.(system|popen)\s*\(', s)},
    {"name": "uses_subprocess_list", "desc": "runs via subprocess with the args list",
     "check": lambda s, r: bool(re.search(r'subprocess\.(run|check_output|check_call|Popen)\s*\(\s*args', s))},
]
