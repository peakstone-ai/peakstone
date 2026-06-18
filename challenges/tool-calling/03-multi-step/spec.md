# Dependent multi-step tool calls

Tests chaining tools where the second call depends on the first's result.

Tools: `get_user(user_id)` → `{name, city}`, and `get_population(city)` → number. The model
must find the population of the city where user 7 lives: call `get_user(7)`, feed the returned
city ("Oslo") into `get_population`, and report the result (697000). Defined in `task.py`.
