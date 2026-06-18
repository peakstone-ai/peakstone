from solution import shortest_path_len


def test_basic_distance():
    g = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    assert shortest_path_len(g, "a", "d") == 2


def test_start_equals_goal():
    g = {"a": ["b"], "b": []}
    assert shortest_path_len(g, "a", "a") == 0


def test_unreachable():
    g = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    assert shortest_path_len(g, "d", "a") == -1


def test_direct_edge():
    g = {"x": ["y"], "y": []}
    assert shortest_path_len(g, "x", "y") == 1


def test_picks_shortest_of_multiple_paths():
    # a->b->c->goal (len 3) vs a->goal (len 1)
    g = {"a": ["b", "goal"], "b": ["c"], "c": ["goal"], "goal": []}
    assert shortest_path_len(g, "a", "goal") == 1


def test_handles_cycles():
    g = {"a": ["b"], "b": ["a", "c"], "c": []}
    assert shortest_path_len(g, "a", "c") == 2


def test_neighbor_without_own_key():
    # "c" appears as a neighbor but has no key of its own
    g = {"a": ["b"], "b": ["c"]}
    assert shortest_path_len(g, "a", "c") == 2
    assert shortest_path_len(g, "c", "a") == -1


def test_goal_not_in_graph_at_all():
    g = {"a": ["b"], "b": []}
    assert shortest_path_len(g, "a", "z") == -1
