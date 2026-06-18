# Correct tool selection

Tests whether the model picks the right tool from several plausible ones (and avoids the
wrong ones). Given `search_web`, `send_email`, `create_calendar_event`, and `get_current_time`,
the request is to schedule a meeting — so it must call `create_calendar_event` (with the right
title) and must NOT call `send_email` or `search_web`. Defined in `task.py`.
