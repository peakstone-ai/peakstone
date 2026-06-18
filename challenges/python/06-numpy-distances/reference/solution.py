import numpy as np


def pairwise_distances(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    diff = points[:, None, :] - points[None, :, :]
    return np.sqrt((diff ** 2).sum(axis=-1))
