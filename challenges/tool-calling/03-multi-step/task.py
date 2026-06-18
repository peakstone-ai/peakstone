"""Tool-calling task: second call depends on the first call's output."""

SYSTEM = "You are an assistant with tools. Look up whatever you need step by step."
PROMPT = ("What is the population of the city where user 7 lives? "
          "Use the tools to find out, then answer with just the number.")

TOOLS = [
    {"type": "function", "function": {
        "name": "get_user", "description": "Look up a user by id; returns their name and city.",
        "parameters": {"type": "object",
                       "properties": {"user_id": {"type": "integer"}},
                       "required": ["user_id"]}}},
    {"type": "function", "function": {
        "name": "get_population", "description": "Return the population of a city.",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string"}},
                       "required": ["city"]}}},
]

_USERS = {7: {"name": "Dana", "city": "Oslo"}, 3: {"name": "Sam", "city": "Lima"}}
_POP = {"oslo": 697000, "lima": 8852000}


def dispatch(name, args):
    if name == "get_user":
        try:
            uid = int(args.get("user_id"))
        except (TypeError, ValueError):
            return {"error": "user_id must be an integer"}
        return _USERS.get(uid, {"error": "no such user"})
    if name == "get_population":
        city = str(args.get("city", ""))
        pop = _POP.get(city.strip().lower())
        return {"city": city, "population": pop} if pop else {"error": "unknown city"}
    return {"error": f"unknown tool {name}"}


def check(calls, final_text):
    total = 3
    passed = 0
    if any(c["name"] == "get_user" and str(c["arguments"].get("user_id")) == "7" for c in calls):
        passed += 1
    if any(c["name"] == "get_population"
           and "oslo" in str(c["arguments"].get("city", "")).lower() for c in calls):
        passed += 1
    if "697000" in (final_text or "").replace(",", "").replace(".", ""):
        passed += 1
    return passed, total
