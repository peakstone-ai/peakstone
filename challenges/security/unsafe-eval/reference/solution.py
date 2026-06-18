import json


def parse_int_list(text: str) -> list[int]:
    return [int(x) for x in json.loads(text)]
