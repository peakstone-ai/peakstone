# Single tool call (weather)

Tests whether the model invokes a provided tool with correct arguments and uses the result.

The model is given a `get_weather(city)` tool and asked for the current temperature in Paris.
Scored on: (1) it calls `get_weather` with `city = "Paris"`, and (2) its final answer states
the temperature returned by the tool (18). Defined in `task.py`.
