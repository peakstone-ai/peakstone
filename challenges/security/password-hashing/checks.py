import re
RULES = [
    {"name": "strong_kdf", "desc": "uses bcrypt/argon2/scrypt/pbkdf2",
     "check": lambda s, r: bool(re.search(r'bcrypt|argon2|scrypt|pbkdf2', s, re.I))},
    {"name": "no_fast_hash", "desc": "no bare md5/sha* on the password",
     "check": lambda s, r: not re.search(r'\b(md5|sha1|sha224|sha256|sha384|sha512)\s*\(', s, re.I)},
]
