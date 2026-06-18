# Arithmetic via calculator tools

Tests whether the model composes multiple tool calls instead of computing itself.

Given `add(a, b)` and `multiply(a, b)` tools, the model must compute `(3 + 4) * 5` **using
the tools** and report `35`. Scored on: it called `add` with {3,4}, called `multiply` using
the intermediate result and 5, and gave the final answer `35`. Defined in `task.py`.
