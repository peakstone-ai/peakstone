from solution import longest_dependency_chain


def test_linear_chain():
    assert longest_dependency_chain({"a": ["b"], "b": ["c"], "c": []}) == 3


def test_branch():
    deps = {"a": ["b", "c"], "b": ["d"], "c": [], "d": []}
    assert longest_dependency_chain(deps) == 3  # d -> b -> a


def test_single_node():
    assert longest_dependency_chain({"solo": []}) == 1


def test_empty_graph():
    assert longest_dependency_chain({}) == 0


def test_implicit_prereq_nodes():
    # "c" is never a key but is a prerequisite of "b"
    deps = {"a": ["b"], "b": ["c"]}
    assert longest_dependency_chain(deps) == 3


def test_two_disconnected_chains():
    deps = {"a": ["b"], "b": [], "x": ["y"], "y": ["z"], "z": []}
    # longest is x -> y -> z reversed: z -> y -> x = 3
    assert longest_dependency_chain(deps) == 3


def test_diamond():
    deps = {"top": ["l", "r"], "l": ["base"], "r": ["base"], "base": []}
    assert longest_dependency_chain(deps) == 3


def test_all_independent():
    deps = {"a": [], "b": [], "c": []}
    assert longest_dependency_chain(deps) == 1
