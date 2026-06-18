"""Tool-calling task: choose the correct tool among distractors; avoid the wrong ones."""

SYSTEM = "You are an assistant with several tools. Use the single most appropriate tool for the request."
PROMPT = ("Schedule a calendar event titled 'Sync' for 2026-07-01 at 10:00. "
          "Use the appropriate tool.")

TOOLS = [
    {"type": "function", "function": {
        "name": "search_web", "description": "Search the web for a query.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "send_email", "description": "Send an email.",
        "parameters": {"type": "object",
                       "properties": {"to": {"type": "string"}, "subject": {"type": "string"},
                                      "body": {"type": "string"}},
                       "required": ["to", "subject", "body"]}}},
    {"type": "function", "function": {
        "name": "create_calendar_event", "description": "Create a calendar event.",
        "parameters": {"type": "object",
                       "properties": {"title": {"type": "string"},
                                      "date": {"type": "string", "description": "YYYY-MM-DD"},
                                      "time": {"type": "string", "description": "HH:MM"}},
                       "required": ["title", "date", "time"]}}},
    {"type": "function", "function": {
        "name": "get_current_time", "description": "Get the current time.",
        "parameters": {"type": "object", "properties": {}}}},
]


def dispatch(name, args):
    if name == "create_calendar_event":
        return {"ok": True, "id": "evt_1", "title": args.get("title")}
    if name == "search_web":
        return {"results": []}
    if name == "send_email":
        return {"ok": True}
    if name == "get_current_time":
        return {"now": "2026-06-30T12:00:00"}
    return {"error": f"unknown tool {name}"}


def check(calls, final_text):
    total = 2
    passed = 0
    names = [c["name"] for c in calls]
    if any(c["name"] == "create_calendar_event"
           and "sync" in str(c["arguments"].get("title", "")).lower() for c in calls):
        passed += 1
    if "send_email" not in names and "search_web" not in names:
        passed += 1
    return passed, total
