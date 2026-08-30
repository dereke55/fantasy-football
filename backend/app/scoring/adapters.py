"""Translate upstream rows into internal stat lines. Strict: a missing REQUIRED upstream column raises (never silently 0)."""
from __future__ import annotations

from collections.abc import Mapping

# internal key -> candidate upstream column names (first present wins)
NFLVERSE_WEEK = {
    "pass_yd": ("passing_yards",),
    "pass_td": ("passing_tds",),
    "pass_int": ("passing_interceptions", "interceptions"),
    "pass_2pt": ("passing_2pt_conversions",),
    "rush_yd": ("rushing_yards",),
    "rush_td": ("rushing_tds",),
    "rush_2pt": ("rushing_2pt_conversions",),
    "rec": ("receptions",),
    "rec_yd": ("receiving_yards",),
    "rec_td": ("receiving_tds",),
    "rec_2pt": ("receiving_2pt_conversions",),
    "fum_lost": ("fumbles_lost_total", "sack_fumbles_lost+rushing_fumbles_lost+receiving_fumbles_lost"),
    "ret_td": ("special_teams_tds",),
}

FF_OPPORTUNITY_EXP = {
    "pass_yd": ("pass_yards_gained_exp",),
    "pass_td": ("pass_touchdown_exp",),
    "pass_int": ("pass_interception_exp",),
    "pass_2pt": ("pass_two_point_conv_exp",),
    "rush_yd": ("rush_yards_gained_exp",),
    "rush_td": ("rush_touchdown_exp",),
    "rush_2pt": ("rush_two_point_conv_exp",),
    "rec": ("receptions_exp",),
    "rec_yd": ("rec_yards_gained_exp",),
    "rec_td": ("rec_touchdown_exp",),
    "rec_2pt": ("rec_two_point_conv_exp",),
    "fum_lost": ("rush_fumble_lost_exp+rec_fumble_lost_exp",),
    "ret_td": (),
}

SLEEPER = {
    "pass_yd": ("stat_pass_yd", "pass_yd"),
    "pass_td": ("stat_pass_td", "pass_td"),
    "pass_int": ("stat_pass_int", "pass_int"),
    "pass_2pt": ("stat_pass_2pt", "pass_2pt"),
    "rush_yd": ("stat_rush_yd", "rush_yd"),
    "rush_td": ("stat_rush_td", "rush_td"),
    "rush_2pt": ("stat_rush_2pt", "rush_2pt"),
    "rec": ("stat_rec", "rec"),
    "rec_yd": ("stat_rec_yd", "rec_yd"),
    "rec_td": ("stat_rec_td", "rec_td"),
    "rec_2pt": ("stat_rec_2pt", "rec_2pt"),
    "fum_lost": ("stat_fum_lost", "fum_lost"),
    "ret_td": ("stat_st_td", "st_td"),
}

# keys that must exist for a row to be scorable at all (others default to 0 when absent, e.g. ret_td in expected stats)
REQUIRED = {"pass_yd", "pass_td", "rush_yd", "rush_td", "rec", "rec_yd", "rec_td"}


class MissingStatColumn(KeyError):
    pass


def _get(row: Mapping, candidates: tuple[str, ...]) -> float | None:
    for c in candidates:
        if "+" in c:
            parts = c.split("+")
            if all(p in row for p in parts):
                return float(sum((row.get(p) or 0) for p in parts))
            continue
        if c in row:
            v = row[c]
            return float(v) if v is not None else 0.0
    return None


def to_stat_line(row: Mapping, mapping: dict[str, tuple[str, ...]], *, strict: bool = True) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, cands in mapping.items():
        v = _get(row, cands) if cands else None
        if v is None:
            if strict and key in REQUIRED:
                raise MissingStatColumn(f"{key}: none of {cands} present in row keys {sorted(row.keys())[:12]}...")
            v = 0.0
        out[key] = v
    return out


def from_nflverse_week(row: Mapping, *, strict: bool = True) -> dict[str, float]:
    return to_stat_line(row, NFLVERSE_WEEK, strict=strict)


def from_ff_opportunity_expected(row: Mapping, *, strict: bool = True) -> dict[str, float]:
    return to_stat_line(row, FF_OPPORTUNITY_EXP, strict=strict)


def from_sleeper_projection(row: Mapping, *, strict: bool = True) -> dict[str, float]:
    return to_stat_line(row, SLEEPER, strict=strict)
