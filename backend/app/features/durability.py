"""Phase 3 — durability features (REG only, seasons passed explicitly).

Two entry points:

``compute(seasons)``          one row per (player_id, gsis_id, season) — the per-season availability ledger.
``compute_summary(seasons)``  one row per hub QB/RB/WR/TE — the 3-season roll-up plus E[games] and bio, with
                              nulls (never missing rows) for players who have no history.

Sources (all real, all REG):
  ``raw_nflverse_roster_weekly``      week-by-week roster status  -> eligible_games
  ``raw_nflverse_stats_player_week``  week-by-week stat lines     -> games_played
  ``raw_nflverse_injuries``           weekly injury report        -> injury spells / causes
  ``raw_sleeper_players``             today's injury designation  -> current_injury_status / body_part
  ``backend/seeds/known_missed_weeks.yaml``                       -> known_missed_weeks (43 curated rows)

Roster-status inclusion rule (verified against the values actually present in
``raw_nflverse_roster_weekly`` for 2023-2025 REG — 77 distinct ``status`` x ``status_description_abbr`` pairs):

  A week is ELIGIBLE when ``status`` is one of ACT / INA / RES / PUP — i.e. the player was under contract on the
  53-man roster (ACT), on the 53-man roster but a gameday inactive (INA), or on a reserve list that a healthy
  player never lands on (RES = injured reserve, PUP, NFI) — AND ``status_description_abbr`` is not one of the
  "not available for football reasons" codes below:

    prefix P**  practice squad / development (P01 P02 P03 P04 P06 P07)
    prefix W**  waived (W03 W04)          prefix E**  commissioner-exempt list (E01 E02 E14)     F01 free agent
    R02         reserve/retired           R03  reserve/did-not-report (holdout: Chris Jones '23, Reddick '24)
    R06         reserve/left squad        R09  legacy/bad rows (three 1960s names in the 2025 file)
    R30 R33 R40 suspended (R40 = commissioner suspension — Rice '25 wk 1-6, Kamara '23 wk 1-3, J.Williams '23
                wk 1-4; R30 = indefinite gambling suspensions '23; R33 = club suspension)

  Kept as eligible: A01 (active), I01/I02 (inactive, incl. the emergency-3rd-QB rule), R01 (reserve/injured),
  R04 (reserve/PUP), R05 (reserve/NFI), R27/R47 (reserve/non-football illness), R48 (IR-designated-to-return),
  R34/R36/R49 (rare injury-settlement style reserve codes).

  Bye weeks need no special handling: nflverse simply omits the bye week from ``roster_weekly``, so the
  eligible-week set is already bye-free (verified: Kamara has no 2023 week 11 row, Rice no 2025 week 10 row).

Statuses that are EXCLUDED are "unknown", never "missed" — they do not enter eligible_games at all.
"""
from __future__ import annotations

import functools
from datetime import date, timedelta

import polars as pl
import yaml

from app.config import settings
from app.db import engine
from app.ranking.adjustments import SEASON_GAMES, expected_games

# ------------------------------------------------------------------ constants

KICKOFF_2026 = date(2026, 9, 10)
FANTASY_POSITIONS = ("QB", "RB", "WR", "TE")

# First REG Sunday-week anchor per season; a week-W injury listing is dated week1 + (W-1)*7 days.
# nflverse ships date_modified for 2023/2024 only (it is NULL for every 2025 row), so listing dates are
# derived from (season, week) for ALL seasons to keep the rule uniform and reproducible.
SEASON_WEEK1 = {2023: date(2023, 9, 7), 2024: date(2024, 9, 5), 2025: date(2025, 9, 4)}

ELIGIBLE_STATUS = ("ACT", "INA", "RES", "PUP")
EXCLUDED_DESC_PREFIX = ("P", "W", "E", "F")
EXCLUDED_DESC = ("R02", "R03", "R06", "R09", "R30", "R33", "R40")

# An injury-report row counts toward a spell when the game status is one of these ...
REPORT_STATUSES = ("Out", "Doubtful", "Questionable")
# ... or the practice line says the player was limited / did not practise.
PRACTICE_LIMITED_RE = r"(?i)did not participate|limited participation"

# A one-week hole (bye week, or a week the club simply did not list the player) does NOT split a spell;
# a gap of two or more listed weeks does.
MAX_SPELL_GAP = 2

SOFT_TISSUE_RE = r"(?i)hamstring|groin|calf|quad|soft tissue"
STRUCTURAL_RE = r"(?i)\bacl\b|achilles|\bmcl\b|\bpcl\b|patell|fracture|torn"
UNSPECIFIED = "Unspecified"
# nflverse writes "Not injury related - resting player / personal matter" in the injury column; those are
# scheduled rest days and leaves of absence, not injuries, so they never open a spell.
NOT_AN_INJURY_RE = r"(?i)^not injury related"

# structural_injury_return: a structural listing counts as season-ending when the player never played again
# that season from the spell's first week onward AND at least this many eligible weeks went unplayed.
SEASON_ENDING_MIN_MISSED = 4
# ... and the discount only applies when the LAST listing of that spell is inside 12 months of kickoff.
STRUCTURAL_LOOKBACK_DAYS = 365

INJURY_PRONE_MISS_RATE = 0.20
INJURY_PRONE_MIN_EVENTS = 2
INJURY_PRONE_MIN_SEASONS = 2
TOP_CAUSES = 3


def _q(sql: str) -> pl.DataFrame:
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


def _seasons_sql(seasons: list[int]) -> str:
    return ", ".join(str(int(s)) for s in seasons)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


# ------------------------------------------------------------------ hub / seed loaders

def hub_players(positions: tuple[str, ...] = FANTASY_POSITIONS) -> pl.DataFrame:
    """The players hub restricted to fantasy positions (one row per player_id)."""
    return _q(
        "select id as player_id, gsis_id, sleeper_id, name, position, team, birth_date, years_exp, "
        "is_rookie, draft_round, draft_pick "
        f"from players where position in ({_in_list(positions)}) order by id"
    )


@functools.cache
def known_missed_weeks() -> dict[str, int]:
    """gsis_id -> announced 2026 REG weeks missed, from backend/seeds/known_missed_weeks.yaml (43 rows)."""
    path = settings.seeds_dir / "known_missed_weeks.yaml"
    doc = yaml.safe_load(path.read_text()) or {}
    out: dict[str, int] = {}
    for row in doc.get("rows", []):
        gsis = row.get("gsis_id")
        if gsis:
            out[str(gsis)] = int(row.get("known_missed_weeks") or 0)
    return out


# ------------------------------------------------------------------ building blocks

def eligible_weeks(seasons: list[int]) -> pl.DataFrame:
    """(gsis_id, season, week) for every REG week the player was on the active/injured roster.

    See the module docstring for the exact status rule."""
    sql = (
        "select gsis_id, season, week from raw_nflverse_roster_weekly "
        f"where game_type = 'REG' and season in ({_seasons_sql(seasons)}) and gsis_id is not null "
        f"and status in ({_in_list(ELIGIBLE_STATUS)}) "
        "and (status_description_abbr is null or (left(status_description_abbr, 1) not in "
        f"({_in_list(EXCLUDED_DESC_PREFIX)}) and status_description_abbr not in ({_in_list(EXCLUDED_DESC)}))) "
        "group by 1, 2, 3"
    )
    return _q(sql).with_columns(pl.col("season").cast(pl.Int32), pl.col("week").cast(pl.Int32))


def played_weeks(seasons: list[int]) -> pl.DataFrame:
    """(gsis_id, season, week) for every REG week with at least one opportunity (target/carry/pass attempt)."""
    sql = (
        "select player_id as gsis_id, season, week from raw_nflverse_stats_player_week "
        f"where season_type = 'REG' and season in ({_seasons_sql(seasons)}) and player_id is not null "
        "and (coalesce(targets, 0) + coalesce(carries, 0) + coalesce(attempts, 0)) >= 1 "
        "group by 1, 2, 3"
    )
    return _q(sql).with_columns(pl.col("season").cast(pl.Int32), pl.col("week").cast(pl.Int32))


def injury_spells(seasons: list[int]) -> pl.DataFrame:
    """One row per distinct injury spell: (gsis_id, season, cause, spell, first_week, last_week, weeks_listed).

    A spell = consecutive REG weeks sharing the same injury text on which the player was listed
    Out / Doubtful / Questionable, or was limited / did not participate in practice. A single missing week
    (bye, or an unlisted week) bridges the spell; two or more start a new one.

    ``cause`` is ``report_primary_injury`` falling back to ``practice_primary_injury``: 9,084 of the 17,188
    REG rows are mid-week practice reports that carry no game designation and therefore no
    ``report_primary_injury``, and dropping their injury text would bucket most spells as "Unspecified".

    REG is filtered on ``game_type`` — ``season_type`` is NULL for every 2023 and 2024 row (verified)."""
    sql = (
        "select season, week, gsis_id, report_primary_injury, practice_primary_injury, report_status, "
        "practice_status from raw_nflverse_injuries "
        f"where game_type = 'REG' and season in ({_seasons_sql(seasons)}) and gsis_id is not null"
    )
    df = _q(sql)
    schema = {
        "gsis_id": pl.String, "season": pl.Int32, "cause": pl.String, "spell": pl.Int32,
        "first_week": pl.Int32, "last_week": pl.Int32, "weeks_listed": pl.UInt32,
    }
    if df.is_empty():
        return pl.DataFrame(schema=schema)

    df = df.with_columns(
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        report_status=pl.col("report_status").fill_null("").str.strip_chars(),
        practice_status=pl.col("practice_status").fill_null("").str.strip_chars(),
        cause=pl.coalesce(
            pl.col("report_primary_injury").str.strip_chars().replace("", None),
            pl.col("practice_primary_injury").str.strip_chars().replace("", None),
        ).fill_null(UNSPECIFIED),
    )
    qual = df.filter(
        (
            pl.col("report_status").is_in(REPORT_STATUSES)
            | pl.col("practice_status").str.contains(PRACTICE_LIMITED_RE)
        )
        & ~pl.col("cause").str.contains(NOT_AN_INJURY_RE)
    )
    if qual.is_empty():
        return pl.DataFrame(schema=schema)

    key = ["gsis_id", "season", "cause"]
    qual = (
        qual.unique(subset=[*key, "week"])
        .sort([*key, "week"])
        .with_columns(gap=(pl.col("week") - pl.col("week").shift(1)).over(key))
        .with_columns(new_spell=(pl.col("gap").is_null() | (pl.col("gap") > MAX_SPELL_GAP)).cast(pl.Int32))
        .with_columns(spell=pl.col("new_spell").cum_sum().over(key).cast(pl.Int32))
    )
    return (
        qual.group_by([*key, "spell"])
        .agg(
            first_week=pl.col("week").min(),
            last_week=pl.col("week").max(),
            weeks_listed=pl.len(),
        )
        .sort([*key, "spell"])
        .cast(schema)
    )


# ------------------------------------------------------------------ per-season table

def compute(seasons: list[int] | None = None) -> pl.DataFrame:
    """One row per (player_id, gsis_id, season) for hub QB/RB/WR/TE with any REG footprint that season.

    Columns: player_id, gsis_id, name, position, season, eligible_games, games_played, games_missed,
    injury_events, injury_causes, soft_tissue_listings, structural_listings.

    ``games_missed = max(0, eligible_games - games_played)``. Note that "played" means >= 1 target, carry or
    pass attempt, so a healthy backup QB or a blocking TE registers as missed weeks — this column measures
    availability-with-opportunity, not snaps."""
    seasons = list(seasons or settings.history_seasons)
    hub = hub_players()
    elig = eligible_weeks(seasons)
    played = played_weeks(seasons)
    spells = injury_spells(seasons)

    elig_n = elig.group_by(["gsis_id", "season"]).agg(eligible_games=pl.len().cast(pl.Int32))
    # only weeks the player was ALSO eligible count as played, so a stat line logged while on the practice
    # squad (or for a club he was cut from) cannot push games_played above eligible_games
    played_n = (
        played.join(elig, on=["gsis_id", "season", "week"], how="inner")
        .group_by(["gsis_id", "season"])
        .agg(games_played=pl.len().cast(pl.Int32))
    )
    inj_n = spells.group_by(["gsis_id", "season"]).agg(
        injury_events=pl.len().cast(pl.Int32),
        injury_causes=pl.col("cause").unique().sort(),
        soft_tissue_listings=pl.col("cause").str.contains(SOFT_TISSUE_RE).sum().cast(pl.Int32),
        structural_listings=pl.col("cause").str.contains(STRUCTURAL_RE).sum().cast(pl.Int32),
    )

    keys = pl.concat(
        [elig.select("gsis_id", "season"), played.select("gsis_id", "season"), spells.select("gsis_id", "season")]
    ).unique()

    out = (
        hub.select("player_id", "gsis_id", "name", "position")
        .drop_nulls("gsis_id")
        .join(keys, on="gsis_id", how="inner")
        .join(elig_n, on=["gsis_id", "season"], how="left")
        .join(played_n, on=["gsis_id", "season"], how="left")
        .join(inj_n, on=["gsis_id", "season"], how="left")
        .with_columns(
            eligible_games=pl.col("eligible_games").fill_null(0),
            games_played=pl.col("games_played").fill_null(0),
            injury_events=pl.col("injury_events").fill_null(0),
            soft_tissue_listings=pl.col("soft_tissue_listings").fill_null(0),
            structural_listings=pl.col("structural_listings").fill_null(0),
            injury_causes=pl.col("injury_causes").fill_null(pl.lit([], dtype=pl.List(pl.String))),
        )
        .with_columns(
            games_missed=pl.max_horizontal(pl.col("eligible_games") - pl.col("games_played"), pl.lit(0)).cast(pl.Int32)
        )
        .select(
            "player_id", "gsis_id", "name", "position", "season", "eligible_games", "games_played",
            "games_missed", "injury_events", "injury_causes", "soft_tissue_listings", "structural_listings",
        )
        .sort(["player_id", "season"])
    )
    return out


# ------------------------------------------------------------------ structural / current status helpers

def _structural_returns(seasons: list[int]) -> pl.DataFrame:
    """gsis_id -> structural_injury_return (bool) + the supporting spell, for season-ending structural
    injuries whose LAST weekly listing falls within 12 months of the 2026-09-10 kickoff.

    "Season-ending" = the player logged no opportunity in any eligible week from the spell's first week to
    the end of that season, and at least SEASON_ENDING_MIN_MISSED eligible weeks went unplayed."""
    spells = injury_spells(seasons).filter(pl.col("cause").str.contains(STRUCTURAL_RE))
    schema = {
        "gsis_id": pl.String, "structural_injury_return": pl.Boolean,
        "structural_cause": pl.String, "structural_season": pl.Int32, "structural_last_listed": pl.Date,
    }
    if spells.is_empty():
        return pl.DataFrame(schema=schema)

    elig = eligible_weeks(seasons)
    played = played_weeks(seasons)
    remaining = (
        elig.join(played.with_columns(played=pl.lit(True)), on=["gsis_id", "season", "week"], how="left")
        .with_columns(played=pl.col("played").fill_null(False))
    )
    cand = spells.join(remaining, on=["gsis_id", "season"], how="inner").filter(
        pl.col("week") >= pl.col("first_week")
    )
    agg = cand.group_by(["gsis_id", "season", "cause", "spell", "last_week"]).agg(
        weeks_after=pl.len(),
        played_after=pl.col("played").sum(),
    )
    week1 = pl.col("season").replace_strict(SEASON_WEEK1, default=None, return_dtype=pl.Date)
    cutoff = KICKOFF_2026 - timedelta(days=STRUCTURAL_LOOKBACK_DAYS)
    agg = agg.with_columns(
        last_listed=week1 + pl.duration(days=(pl.col("last_week") - 1) * 7)
    ).filter(
        (pl.col("played_after") == 0)
        & ((pl.col("weeks_after") - pl.col("played_after")) >= SEASON_ENDING_MIN_MISSED)
        & (pl.col("last_listed") >= pl.lit(cutoff))
    )
    if agg.is_empty():
        return pl.DataFrame(schema=schema)
    return (
        agg.sort(["gsis_id", "last_listed"], descending=[False, True])
        .group_by("gsis_id")
        .first()
        .select(
            "gsis_id",
            structural_injury_return=pl.lit(True),
            structural_cause=pl.col("cause"),
            structural_season=pl.col("season").cast(pl.Int32),
            structural_last_listed=pl.col("last_listed"),
        )
        .cast(schema)
    )


def _trailing_absence(season: int) -> pl.DataFrame:
    """gsis_id -> trailing_missed: the run of unplayed eligible weeks that closes out `season`.

    A player whose season ends on injured reserve has a trailing run equal to the length of the IR stint."""
    elig = eligible_weeks([season])
    played = played_weeks([season]).with_columns(played=pl.lit(value=True))
    weeks = (
        elig.join(played, on=["gsis_id", "season", "week"], how="left")
        .with_columns(played=pl.col("played").fill_null(value=False))
        .sort(["gsis_id", "week"], descending=[False, True])
    )
    return (
        weeks.group_by("gsis_id")
        .agg(trailing_missed=pl.col("played").cum_sum().eq(0).sum().cast(pl.Int32))
        .select("gsis_id", "trailing_missed")
    )


def _sleeper_status() -> pl.DataFrame:
    """sleeper_id -> today's injury designation (raw_sleeper_players snapshot, once/day)."""
    df = _q(
        "select player_id as sleeper_id, nullif(trim(injury_status), '') as current_injury_status, "
        "nullif(trim(injury_body_part), '') as current_injury_body_part "
        "from raw_sleeper_players where player_id is not null"
    )
    if df.is_empty():
        return pl.DataFrame(schema={
            "sleeper_id": pl.String, "current_injury_status": pl.String, "current_injury_body_part": pl.String,
        })
    return df.with_columns(pl.col("sleeper_id").cast(pl.String)).unique(subset=["sleeper_id"])


# ------------------------------------------------------------------ 3-season summary

def compute_summary(seasons: list[int] | None = None) -> pl.DataFrame:
    """One row per hub QB/RB/WR/TE (no-history players get nulls, never missing rows).

    Columns: player_id, gsis_id, name, position, team, games_missed_3yr, games_eligible_3yr, miss_rate_3yr,
    injury_events_3yr, seasons_with_injury_events, seasons_with_soft_tissue, injury_causes, injury_prone,
    structural_injury_return, structural_cause, structural_season, current_injury_status,
    current_injury_body_part, known_missed_weeks, e_games, e_games_detail, age_2026, years_exp, is_rookie,
    draft_round, draft_pick.

    injury_prone = (miss_rate_3yr >= 0.20 AND >= 2 injury events spread over >= 2 distinct seasons)
                   OR (>= 2 soft-tissue spells in different seasons).

    structural_injury_return marks a player coming back from a RECENT season-ending structural injury
    (ACL / Achilles / MCL / PCL / patellar / fracture / "torn"). Two paths, because a player placed straight
    on IR disappears from the weekly injury report altogether (Malik Nabers' 2025 ACL is nowhere in
    raw_nflverse_injuries — his last listings are a Back and a Shoulder in weeks 1-4):
      report path  a season-ending structural spell whose last weekly listing is on or after
                   2026-09-10 minus 365 days, i.e. inside 12 months of kickoff (see _structural_returns);
      sleeper path today's Sleeper `injury_body_part` names a structural injury AND the player's last
                   history season (max(seasons)) ended in a run of >= 4 unplayed eligible weeks.
    Both paths exclude players already ruled out for all of 2026 (known_missed_weeks >= 17) — those are not
    "returning", and e_games already zeroes them out.

    e_games      = app.ranking.adjustments.expected_games(position, adp_round=None, hist_missed=...,
                   hist_eligible=..., known_missed_weeks=...). adp_round is None until the Phase 4-lite
                   composite exists, so every player currently uses the middle (rounds 3-5) base band."""
    seasons = list(seasons or settings.history_seasons)
    hub = hub_players()
    per_season = compute(seasons)
    spells = injury_spells(seasons)

    totals = per_season.group_by("player_id").agg(
        games_missed_3yr=pl.col("games_missed").sum().cast(pl.Int32),
        games_eligible_3yr=pl.col("eligible_games").sum().cast(pl.Int32),
        injury_events_3yr=pl.col("injury_events").sum().cast(pl.Int32),
        seasons_with_injury_events=(pl.col("injury_events") > 0).sum().cast(pl.Int32),
        seasons_with_soft_tissue=(pl.col("soft_tissue_listings") > 0).sum().cast(pl.Int32),
        soft_tissue_spells=pl.col("soft_tissue_listings").sum().cast(pl.Int32),
    )
    # top-3 causes by number of spells across the window
    causes = (
        spells.group_by(["gsis_id", "cause"])
        .agg(n=pl.len())
        .sort(["gsis_id", "n", "cause"], descending=[False, True, False])
        .group_by("gsis_id", maintain_order=True)
        .head(TOP_CAUSES)
        .group_by("gsis_id")
        .agg(injury_causes=pl.col("cause"))
    )

    df = (
        hub.join(totals, on="player_id", how="left")
        .join(causes, on="gsis_id", how="left")
        .join(_structural_returns(seasons), on="gsis_id", how="left")
        .join(_trailing_absence(max(seasons)), on="gsis_id", how="left")
        .join(_sleeper_status(), on="sleeper_id", how="left")
        .with_columns(
            known_missed_weeks=pl.col("gsis_id").replace_strict(
                known_missed_weeks(), default=0, return_dtype=pl.Int32
            ),
        )
        .with_columns(
            structural_injury_return=(
                pl.col("structural_injury_return").fill_null(value=False)
                | (
                    pl.col("current_injury_body_part").fill_null("").str.contains(STRUCTURAL_RE)
                    & (pl.col("trailing_missed").fill_null(0) >= SEASON_ENDING_MIN_MISSED)
                )
            )
            & (pl.col("known_missed_weeks") < SEASON_GAMES),
            structural_cause=pl.coalesce(pl.col("structural_cause"), pl.col("current_injury_body_part")),
            structural_season=pl.coalesce(
                pl.col("structural_season"),
                pl.when(pl.col("trailing_missed").fill_null(0) >= SEASON_ENDING_MIN_MISSED)
                .then(pl.lit(max(seasons), dtype=pl.Int32))
                .otherwise(None),
            ),
        )
        .with_columns(
            structural_cause=pl.when(pl.col("structural_injury_return")).then(pl.col("structural_cause")),
            structural_season=pl.when(pl.col("structural_injury_return")).then(pl.col("structural_season")),
        )
        .with_columns(
            miss_rate_3yr=pl.when(pl.col("games_eligible_3yr") > 0)
            .then(pl.col("games_missed_3yr") / pl.col("games_eligible_3yr"))
            .otherwise(None)
            .round(4),
            age_2026=pl.when(pl.col("birth_date").is_not_null())
            .then((pl.lit(KICKOFF_2026) - pl.col("birth_date")).dt.total_days() / 365.25)
            .otherwise(None)
            .round(2),
        )
        .with_columns(
            injury_prone=(
                (
                    (pl.col("miss_rate_3yr") >= INJURY_PRONE_MISS_RATE)
                    & (pl.col("injury_events_3yr") >= INJURY_PRONE_MIN_EVENTS)
                    & (pl.col("seasons_with_injury_events") >= INJURY_PRONE_MIN_SEASONS)
                )
                | (
                    (pl.col("soft_tissue_spells") >= INJURY_PRONE_MIN_EVENTS)
                    & (pl.col("seasons_with_soft_tissue") >= INJURY_PRONE_MIN_SEASONS)
                )
            ).fill_null(value=False)
        )
    )

    e_games: list[float] = []
    e_detail: list[dict] = []
    for row in df.select(
        "position", "games_missed_3yr", "games_eligible_3yr", "known_missed_weeks"
    ).iter_rows(named=True):
        value, detail = expected_games(
            row["position"],
            adp_round=None,
            hist_missed=row["games_missed_3yr"],
            hist_eligible=row["games_eligible_3yr"],
            known_missed_weeks=int(row["known_missed_weeks"] or 0),
        )
        e_games.append(value)
        e_detail.append(detail)

    return (
        df.with_columns(
            e_games=pl.Series("e_games", e_games, dtype=pl.Float64),
            e_games_detail=pl.Series("e_games_detail", e_detail),
        )
        .select(
            "player_id", "gsis_id", "name", "position", "team",
            "games_missed_3yr", "games_eligible_3yr", "miss_rate_3yr",
            "injury_events_3yr", "seasons_with_injury_events", "seasons_with_soft_tissue", "injury_causes",
            "injury_prone", "structural_injury_return", "structural_cause", "structural_season",
            "current_injury_status", "current_injury_body_part", "known_missed_weeks",
            "e_games", "e_games_detail",
            "age_2026", "years_exp", "is_rookie", "draft_round", "draft_pick",
        )
        .sort("player_id")
    )
