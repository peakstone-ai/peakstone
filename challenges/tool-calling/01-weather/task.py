"""Tool-calling task: single tool, correct argument, use the result."""

SYSTEM = "You are an assistant with access to tools. Use them when they are needed."
PROMPT = "What is the current temperature in Paris? Call the weather tool, then tell me the temperature in Celsius."

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'Paris'"},
            },
            "required": ["city"],
        },
    },
}]

_TEMP_C = 18


def dispatch(name, args):
    if name == "get_weather":
        return {"city": args.get("city", ""), "temp_c": _TEMP_C, "conditions": "cloudy"}
    return {"error": f"unknown tool {name}"}


def check(calls, final_text):
    total = 2
    passed = 0
    wcalls = [c for c in calls if c["name"] == "get_weather"]
    if any("paris" in str(c["arguments"].get("city", "")).lower() for c in wcalls):
        passed += 1
    if "18" in (final_text or ""):
        passed += 1
    return passed, total
