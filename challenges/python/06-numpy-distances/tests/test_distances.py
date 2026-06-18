import numpy as np
from solution import pairwise_distances


def test_simple():
    pts = np.array([[0.0, 0.0], [3.0, 4.0]])
    d = pairwise_distances(pts)
    assert isinstance(d, np.ndarray)
    assert d.shape == (2, 2)
    np.testing.assert_allclose(d, [[0.0, 5.0], [5.0, 0.0]], atol=1e-9)


def test_symmetric_zero_diagonal():
    rng = np.random.default_rng(0)
    pts = rng.standard_normal((6, 3))
    d = pairwise_distances(pts)
    assert d.shape == (6, 6)
    np.testing.assert_allclose(d, d.T, atol=1e-9)
    np.testing.assert_allclose(np.diag(d), np.zeros(6), atol=1e-9)


def test_matches_bruteforce():
    rng = np.random.default_rng(42)
    pts = rng.standard_normal((5, 4))
    d = pairwise_distances(pts)
    for i in range(5):
        for j in range(5):
            expected = np.sqrt(((pts[i] - pts[j]) ** 2).sum())
            assert abs(d[i, j] - expected) < 1e-9
