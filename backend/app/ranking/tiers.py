"""Tiers: (1) 1-D Gaussian mixture on positional ECR average with fixed k (Boris Chen method), rank-contiguous;
(2) value tiers from drop-offs in our projection (break when gap >= 0.5 x positional weekly SD)."""
from __future__ import annotations

from itertools import pairwise

import numpy as np

FIXED_K = {"QB": (8, 26), "RB": (10, 40), "WR": (12, 60), "TE": (7, 24), "K": (4, 16), "DEF": (4, 16), "DST": (4, 16)}


def ecr_tiers(ecr_avg: list[float], position: str, *, random_state: int = 0) -> list[int]:
    """Tier (1 = best) per player, input ordered by ECR (ascending avg). Players beyond the window get tier k+1."""
    from sklearn.mixture import GaussianMixture

    k, window = FIXED_K.get(position, (8, 40))
    x = np.asarray(ecr_avg, dtype=float)
    n = min(len(x), window)
    if n == 0:
        return []
    k = min(k, n)
    if k <= 1:
        return [1] * n + [2] * (len(x) - n)
    gm = GaussianMixture(n_components=k, random_state=random_state, n_init=3).fit(x[:n].reshape(-1, 1))
    order = np.argsort(gm.means_.ravel())
    remap = {int(comp): rank + 1 for rank, comp in enumerate(order)}
    labels = [remap[int(c)] for c in gm.predict(x[:n].reshape(-1, 1))]
    # enforce rank-contiguity: tiers never go back up as rank worsens
    tiers, cur = [], 1
    for t in labels:
        cur = max(cur, t)
        tiers.append(cur)
    return tiers + [tiers[-1] + 1] * (len(x) - n)


def value_tiers(values: list[float], weekly_sd: float, *, factor: float = 0.5) -> list[int]:
    """Tier per player from drop-offs; input ordered by value descending."""
    if not values:
        return []
    thresh = factor * weekly_sd
    tiers, cur = [1], 1
    for prev, val in pairwise(values):
        if prev - val >= thresh:
            cur += 1
        tiers.append(cur)
    return tiers
