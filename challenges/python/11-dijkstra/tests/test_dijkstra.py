import math

import pytest

from solution import dijkstra


def test_basic_multipath():
    g = {
        "a": [("b", 1.0), ("c", 4.0)],
        "b": [("c", 2.0), ("d", 5.0)],
        "c": [("d", 1.0)],
        "d": [],
    }
    out = dijkstra(g, "a")
    assert out == {"a": 0.0, "b": 1.0, "c": 3.0, "d": 4.0}


def test_start_distance_zero():
    g = {"a": [("b", 7.0)], "b": []}
    out = dijkstra(g, "a")
    assert out["a"] == 0.0


def test_unreachable_omitted():
    g = {"a": [("b", 2.0)], "b": [], "island": [("a", 1.0)]}
    out = dijkstra(g, "a")
    assert out == {"a": 0.0, "b": 2.0}
    assert "island" not in out


def test_chooses_cheaper_route():
    # direct a->c is 10, but a->b->c is 3
    g = {
        "a": [("b", 1.0), ("c", 10.0)],
        "b": [("c", 2.0)],
        "c": [],
    }
    out = dijkstra(g, "a")
    assert out["c"] == pytest.approx(3.0)


def test_single_node_no_edges():
    out = dijkstra({"a": []}, "a")
    assert out == {"a": 0.0}


def test_target_only_node_has_no_outgoing():
    # "z" is only an edge target, never a key
    g = {"a": [("z", 5.0)]}
    out = dijkstra(g, "a")
    assert out == {"a": 0.0, "z": 5.0}


def test_zero_weight_edges():
    g = {"a": [("b", 0.0)], "b": [("c", 0.0)], "c": []}
    out = dijkstra(g, "a")
    assert out == {"a": 0.0, "b": 0.0, "c": 0.0}


def test_larger_graph_relaxation():
    g = {
        "s": [("a", 4.0), ("b", 1.0)],
        "b": [("a", 2.0), ("c", 5.0)],
        "a": [("c", 1.0)],
        "c": [("t", 3.0)],
        "t": [],
    }
    out = dijkstra(g, "s")
    # s->b(1)->a(3)->c(4)->t(7)
    assert out["a"] == pytest.approx(3.0)
    assert out["c"] == pytest.approx(4.0)
    assert out["t"] == pytest.approx(7.0)
    assert all(math.isfinite(v) for v in out.values())
