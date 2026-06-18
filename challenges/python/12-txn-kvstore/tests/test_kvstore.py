import pytest

from solution import KVStore


def test_basic_set_get_delete():
    s = KVStore()
    assert s.get("a") is None
    s.set("a", 1)
    s.set("b", 2)
    assert s.get("a") == 1
    assert s.get("b") == 2
    s.delete("a")
    assert s.get("a") is None
    s.delete("missing")  # no-op, must not raise


def test_len_and_keys_sorted():
    s = KVStore()
    s.set("z", 1)
    s.set("a", 1)
    s.set("m", 1)
    assert s.keys() == ["a", "m", "z"]
    assert len(s) == 3
    s.delete("m")
    assert s.keys() == ["a", "z"]
    assert len(s) == 2


def test_transaction_isolation_then_commit():
    s = KVStore()
    s.set("a", 1)
    s.begin()
    s.set("a", 2)
    s.set("b", 3)
    assert s.get("a") == 2
    assert s.get("b") == 3
    s.commit()
    assert s.get("a") == 2
    assert s.get("b") == 3


def test_rollback_discards_changes():
    s = KVStore()
    s.set("a", 1)
    s.begin()
    s.set("a", 99)
    s.set("b", 5)
    s.rollback()
    assert s.get("a") == 1
    assert s.get("b") is None
    assert s.keys() == ["a"]


def test_delete_within_transaction_is_isolated():
    s = KVStore()
    s.set("a", 1)
    s.begin()
    s.delete("a")
    assert s.get("a") is None
    assert s.keys() == []
    assert len(s) == 0
    s.rollback()
    assert s.get("a") == 1  # delete was rolled back


def test_commit_propagates_delete_to_committed_store():
    s = KVStore()
    s.set("a", 1)
    s.begin()
    s.delete("a")
    s.commit()
    assert s.get("a") is None
    assert s.keys() == []


def test_nested_transactions_inner_rollback():
    s = KVStore()
    s.set("a", 1)
    s.begin()
    s.set("a", 2)
    s.set("b", 3)
    s.begin()
    s.delete("a")
    assert s.get("a") is None
    assert s.get("b") == 3
    s.rollback()             # discard inner
    assert s.get("a") == 2   # outer value restored
    s.commit()               # merge outer into committed
    assert s.get("a") == 2
    assert s.get("b") == 3


def test_nested_commit_merges_into_parent_not_base():
    s = KVStore()
    s.begin()
    s.set("a", 1)
    s.begin()
    s.set("a", 2)
    s.set("b", 3)
    s.commit()               # inner -> outer (NOT committed store yet)
    assert s.get("a") == 2
    assert s.get("b") == 3
    s.rollback()             # discard outer -> everything gone
    assert s.get("a") is None
    assert s.get("b") is None
    assert len(s) == 0


def test_commit_without_transaction_raises():
    s = KVStore()
    with pytest.raises(RuntimeError):
        s.commit()


def test_rollback_without_transaction_raises():
    s = KVStore()
    with pytest.raises(RuntimeError):
        s.rollback()


def test_deep_nesting_visibility_and_merge():
    s = KVStore()
    s.set("k", 0)
    for depth in range(1, 6):
        s.begin()
        s.set("k", depth)
        assert s.get("k") == depth
    # commit all five layers down to the base
    for _ in range(5):
        s.commit()
    assert s.get("k") == 5
    assert s.keys() == ["k"]


def test_reset_value_after_delete_in_same_transaction():
    s = KVStore()
    s.set("a", 1)
    s.begin()
    s.delete("a")
    s.set("a", 7)            # re-add after delete within the same transaction
    assert s.get("a") == 7
    s.commit()
    assert s.get("a") == 7
