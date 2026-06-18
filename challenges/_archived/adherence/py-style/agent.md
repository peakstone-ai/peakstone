# AGENTS.md — Python project conventions (MANDATORY)

All Python code in this project MUST follow these rules:

1. **Type hints everywhere.** Every function annotates all of its parameters and its return type.
2. **Docstrings.** Every function's first statement is a docstring (triple-quoted string).
3. **f-strings only.** Use f-strings for string formatting. Never use `%` formatting or `str.format()`.
4. **No `print`.** Never call `print()`. (Use the `logging` module if you must emit output.)
5. **snake_case.** Function names are lower_snake_case.
6. **Standard library only.** Do not import any third-party packages.
