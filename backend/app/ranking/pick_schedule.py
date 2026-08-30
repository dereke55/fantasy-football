"""Snake pick schedule with keeper holes (Yahoo semantics: a keeper occupies its team's pick in the cost round).

Pure functions; no I/O. `overall_pick` numbering includes keeper slots (that is how Yahoo numbers picks);
`live_pick_no` numbers only the picks that will actually be made on the clock.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeeperSpec:
    team_slot: int      # 1..num_teams (draft order position)
    cost_round: int     # round the keeper consumes
    player_id: int | None = None


@dataclass(frozen=True)
class Slot:
    overall_pick: int
    round: int
    team_slot: int
    is_keeper_slot: bool
    keeper_player_id: int | None
    live_pick_no: int | None


def snake_team_for(round_no: int, index_in_round: int, num_teams: int) -> int:
    """Team slot picking at 1-based `index_in_round` of `round_no` (odd rounds ascend, even rounds descend)."""
    return index_in_round if round_no % 2 == 1 else num_teams - index_in_round + 1


def build_pick_schedule(num_teams: int, rounds: int, keepers: list[KeeperSpec] | None = None) -> list[Slot]:
    keepers = keepers or []
    by_slot_round: dict[tuple[int, int], KeeperSpec] = {}
    for k in keepers:
        if not (1 <= k.team_slot <= num_teams):
            raise ValueError(f"team_slot {k.team_slot} out of range 1..{num_teams}")
        if not (1 <= k.cost_round <= rounds):
            raise ValueError(f"cost_round {k.cost_round} out of range 1..{rounds}")
        key = (k.team_slot, k.cost_round)
        if key in by_slot_round:
            raise ValueError(f"two keepers for team {k.team_slot} in round {k.cost_round}")
        by_slot_round[key] = k

    out: list[Slot] = []
    live = 0
    overall = 0
    for r in range(1, rounds + 1):
        for i in range(1, num_teams + 1):
            overall += 1
            t = snake_team_for(r, i, num_teams)
            k = by_slot_round.get((t, r))
            if k is not None:
                out.append(Slot(overall, r, t, True, k.player_id, None))
            else:
                live += 1
                out.append(Slot(overall, r, t, False, None, live))
    return out


def my_picks(schedule: list[Slot], my_slot: int) -> list[Slot]:
    return [s for s in schedule if s.team_slot == my_slot and not s.is_keeper_slot]


def next_live_pick(schedule: list[Slot], my_slot: int, picks_made: int) -> tuple[Slot | None, int]:
    """Given `picks_made` live picks already on the board, return my next live slot and how many live picks
    happen before it (0 = I am on the clock)."""
    upcoming = [s for s in schedule if not s.is_keeper_slot and s.live_pick_no is not None and s.live_pick_no > picks_made]
    for n, s in enumerate(upcoming):
        if s.team_slot == my_slot:
            return s, n
    return None, len(upcoming)


def on_the_clock(schedule: list[Slot], picks_made: int) -> Slot | None:
    for s in schedule:
        if not s.is_keeper_slot and s.live_pick_no == picks_made + 1:
            return s
    return None
