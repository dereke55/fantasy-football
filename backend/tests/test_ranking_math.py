from app.ranking.adjustments import age_factor, expected_games
from app.ranking.availability import Candidate, expected_best_value, p_available, vona
from app.ranking.room_adp import gap_z, our_pick_equivalent, room_adp
from app.ranking.tiers import value_tiers
from app.ranking.vbd import Projection, compute_baselines, value_pool


def _pool():
    # positional PPG ladders (numbers only; identities irrelevant to the math)
    pool = []
    pid = 1
    for pos, n, top, step in (("QB", 20, 22.0, 0.5), ("RB", 40, 18.0, 0.3), ("WR", 60, 17.0, 0.2), ("TE", 20, 12.0, 0.4)):
        for i in range(n):
            pool.append(Projection(pid, pos, round(top - i * step, 2), 16.0))
            pid += 1
    return pool


def test_baselines_flex_and_keepers():
    pool = _pool()
    slots = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}
    b = compute_baselines(pool, num_teams=10, slots=slots, flex_eligible=["RB", "WR", "TE"], bench=6)
    assert b.starters["RB"] == 20 and b.starters["WR"] == 30
    assert sum(b.flex_alloc.values()) == 10  # all 10 FLEX slots allocated
    assert b.vols_rank["RB"] == 20 + b.flex_alloc["RB"]
    # keepers: two RBs kept -> RB baseline moves up by 2
    b2 = compute_baselines(pool[:20] + pool[22:], num_teams=10, slots=slots, flex_eligible=["RB", "WR", "TE"], bench=6,
                           keepers=[(21, "RB"), (22, "RB")])
    assert b2.vols_rank["RB"] == b.vols_rank["RB"] - 2 or b2.flex_alloc["RB"] != b.flex_alloc["RB"]
    vals = value_pool(pool, b)
    assert vals[0].vorp >= vals[1].vorp
    v = next(x for x in vals if x.player_id == 1)
    assert abs(v.season_value - (16 * 22.0 + 1 * b.replacement_ppg["QB"])) < 1e-6
    assert abs(v.vorp - 16 * (22.0 - b.replacement_ppg["QB"])) < 1e-6


def test_availability_and_vona():
    assert abs(p_available(20.0, 5.0, 20) - 0.5) < 1e-9
    assert p_available(None, 5.0, 20) == 1.0
    assert p_available(10.0, 3.0, 30) < 0.01
    c = [Candidate(1, "RB", 100.0, 5.0, 3.0), Candidate(2, "RB", 80.0, 40.0, 5.0), Candidate(3, "RB", 60.0, 90.0, 8.0)]
    eb = expected_best_value(c, at_pick=30)
    assert 75 < eb < 85  # player 1 is gone, player 2 is ~98% available
    v, p, e = vona(Candidate(9, "RB", 90.0, 25.0, 4.0), c, my_next_pick=30)
    assert e == round(eb, 3) and abs(v - (90.0 - eb)) < 1e-3 and p < 0.15


def test_room_adp_and_gap():
    adp = {1: 3.0, 2: 7.5, 3: 12.0, 4: 20.0}
    r = room_adp(adp, kept={2})
    assert r == {1: 1.0, 3: 2.0, 4: 3.0}
    ours = our_pick_equivalent([4, 1, 3, 2], kept={2})
    assert ours == {4: 1.0, 1: 2.0, 3: 3.0}
    assert gap_z(r[4], ours[4], 4.0) == (2.0, 0.5)


def test_age_and_expected_games():
    assert age_factor("RB", 26) == 1.0 and age_factor("RB", 30) == 0.85 and age_factor("QB", 40) == 0.95
    eg, d = expected_games("RB", adp_round=1.5, hist_missed=0, hist_eligible=51)
    assert eg == round(17 - 2.4, 2) and d["extra_missed"] == 0
    eg2, d2 = expected_games("RB", adp_round=1.5, hist_missed=20, hist_eligible=51, known_missed_weeks=4)
    assert eg2 <= 13.0 and d2["extra_missed"] > 0


def test_value_tiers():
    assert value_tiers([20, 19.8, 15, 14.9, 10], weekly_sd=6.0) == [1, 1, 2, 2, 3]
