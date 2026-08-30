"""Room ADP: re-rank an ADP source after removing kept players and map ranks to LIVE pick numbers.

gap   = room_adp - our_pick_equivalent   (>0: the room takes them later than we would -> potential sleeper)
gap_z = gap / sd_adp
"""
from __future__ import annotations


def room_adp(adp_by_player: dict[int, float], kept: set[int]) -> dict[int, float]:
    """Rank remaining players by ADP; room_adp = rank (1-based) == live pick number equivalent."""
    remaining = sorted(((adp, pid) for pid, adp in adp_by_player.items() if pid not in kept and adp is not None))
    return {pid: float(i) for i, (_, pid) in enumerate(remaining, start=1)}


def our_pick_equivalent(our_rank_order: list[int], kept: set[int]) -> dict[int, float]:
    """our overall ranking (best first) restricted to remaining players -> live pick number equivalent."""
    return {pid: float(i) for i, pid in enumerate((p for p in our_rank_order if p not in kept), start=1)}


def gap_z(room: float | None, ours: float | None, sd_adp: float) -> tuple[float | None, float | None]:
    if room is None or ours is None:
        return None, None
    gap = room - ours
    return round(gap, 2), round(gap / max(sd_adp, 1.0), 3)
