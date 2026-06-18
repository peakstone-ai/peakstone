import pandas as pd
from solution import top_n_per_group


def base_df():
    return pd.DataFrame({
        "team": ["a", "a", "a", "b", "b"],
        "name": ["x", "y", "z", "p", "q"],
        "score": [10, 30, 20, 5, 15],
    })


def test_basic_top2():
    df = base_df()
    out = top_n_per_group(df, "team", "score", 2)
    assert list(out.columns) == ["team", "name", "score"]
    assert len(out) == 4
    a = out[out["team"] == "a"]
    assert list(a["score"]) == [30, 20]
    assert list(a["name"]) == ["y", "z"]
    b = out[out["team"] == "b"]
    assert list(b["score"]) == [15, 5]


def test_index_is_rangeindex():
    df = base_df()
    out = top_n_per_group(df, "team", "score", 2)
    assert list(out.index) == [0, 1, 2, 3]


def test_group_smaller_than_n():
    df = base_df()
    out = top_n_per_group(df, "team", "score", 10)
    # all rows kept (3 in a, 2 in b)
    assert len(out) == 5
    assert (out["team"] == "a").sum() == 3
    assert (out["team"] == "b").sum() == 2


def test_n_equals_one():
    df = base_df()
    out = top_n_per_group(df, "team", "score", 1)
    assert len(out) == 2
    assert set(out["name"]) == {"y", "q"}


def test_does_not_mutate_input():
    df = base_df()
    snapshot = df.copy()
    _ = top_n_per_group(df, "team", "score", 2)
    pd.testing.assert_frame_equal(df, snapshot)


def test_group_order_follows_first_appearance():
    df = pd.DataFrame({
        "g": ["z", "a", "z", "a"],
        "v": [1, 2, 3, 4],
    })
    out = top_n_per_group(df, "g", "v", 1)
    # "z" appears first, so it should come first
    assert list(out["g"]) == ["z", "a"]
    assert list(out["v"]) == [3, 4]


def test_preserves_extra_columns():
    df = pd.DataFrame({
        "team": ["a", "a", "b"],
        "score": [1, 2, 3],
        "extra": ["p", "q", "r"],
    })
    out = top_n_per_group(df, "team", "score", 1)
    assert list(out.columns) == ["team", "score", "extra"]
    a = out[out["team"] == "a"].iloc[0]
    assert a["extra"] == "q"
