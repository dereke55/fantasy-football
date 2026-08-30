from app.ranking.pick_schedule import KeeperSpec, build_pick_schedule, my_picks, next_live_pick, on_the_clock


def test_snake_order_10_teams():
    s = build_pick_schedule(10, 16)
    assert len(s) == 160
    assert [x.team_slot for x in s[:10]] == list(range(1, 11))
    assert [x.team_slot for x in s[10:20]] == list(range(10, 0, -1))
    assert s[159].team_slot == 1 and s[159].round == 16  # even round ends at slot 1
    assert s[-1].live_pick_no == 160


def test_keeper_hole_is_flagged_and_skipped_in_live_numbering():
    keepers = [KeeperSpec(team_slot=3, cost_round=2, player_id=42), KeeperSpec(team_slot=7, cost_round=5)]
    s = build_pick_schedule(10, 16, keepers)
    # round 2 descends: slot 3 picks 8th in the round -> overall 18
    hole = s[17]
    assert (hole.overall_pick, hole.round, hole.team_slot) == (18, 2, 3)
    assert hole.is_keeper_slot and hole.keeper_player_id == 42 and hole.live_pick_no is None
    assert s[18].live_pick_no == 18  # next slot continues live numbering without a gap
    assert sum(1 for x in s if not x.is_keeper_slot) == 158
    assert len(my_picks(s, 3)) == 15


def test_next_live_pick_and_on_the_clock():
    s = build_pick_schedule(10, 16, [KeeperSpec(team_slot=5, cost_round=1)])
    # picks 1-4 made; slot 5 kept in round 1, so slot 6 is on the clock
    otc = on_the_clock(s, picks_made=4)
    assert otc is not None and otc.team_slot == 6 and otc.overall_pick == 6
    nxt, before = next_live_pick(s, my_slot=5, picks_made=4)
    # my next live pick is round 2 (overall 16); live picks before it: slots 6..10 in r1 (5) + slot 10..6 in r2 (5)
    assert nxt is not None and nxt.overall_pick == 16 and before == 10
    nxt, before = next_live_pick(s, my_slot=6, picks_made=4)
    assert before == 0 and nxt.overall_pick == 6
