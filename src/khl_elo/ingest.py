"""Read a Kraken schedule export (krakenhockeyleague.com/schedule -> Export CSV)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .divisions import is_ladder

REQUIRED = ["Date", "Away Team", "Away Score", "Home Team", "Home Score", "Away Division", "Home Division"]


def clean_name(value: object) -> str:
    """Normalise a raw team/division string from the export."""
    s = str(value).replace("''", "'").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def name_key(value: object) -> str:
    """Matching key for names: cleaned and case-folded."""
    return clean_name(value).casefold()


def parse_dates(values: pd.Series) -> pd.Series:
    """Kraken exports use '20-Sep-26' or 'Nov 14, 2026'; the ledger uses '2026-11-14'."""
    out = pd.to_datetime(values, format="%Y-%m-%d", errors="coerce")
    for fmt in ("%b %d, %Y", "%d-%b-%y", "%m/%d/%y", "%m/%d/%Y"):
        missing = out.isna()
        if not missing.any():
            break
        out[missing] = pd.to_datetime(values[missing], format=fmt, errors="coerce")
    return out


@dataclass
class Schedule:
    played: pd.DataFrame
    upcoming: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    dropped_non_ladder: int = 0


def load_schedule(path: Path, raw_names: bool = False) -> Schedule:
    """raw_names=True keeps team names byte-for-byte (legacy regression tests only)."""
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False, na_values=[""])
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}. Is this a Kraken schedule export?")
    warnings: list[str] = []

    df = df.copy()
    df["file_row"] = range(len(df))
    for col in ("Away Division", "Home Division") if raw_names else ("Away Team", "Home Team", "Away Division", "Home Division"):
        df[col] = df[col].map(clean_name)
    if "Arena" not in df.columns:
        df["Arena"] = ""
    df["Arena"] = df["Arena"].fillna("").map(clean_name)
    if "Game Type" not in df.columns:
        df["Game Type"] = "REG"
    df["Game Type"] = df["Game Type"].fillna("")

    df["date"] = parse_dates(df["Date"])
    bad = df["date"].isna()
    if bad.any():
        warnings.append(f"{bad.sum()} rows with unparseable dates dropped: {df.loc[bad, 'Date'].unique()[:5].tolist()}")
        df = df.loc[~bad]

    ladder = df["Away Division"].map(is_ladder) & df["Home Division"].map(is_ladder)
    half = df["Away Division"].map(is_ladder) ^ df["Home Division"].map(is_ladder)
    if half.any():
        warnings.append(
            f"{half.sum()} games between a ladder and a non-ladder division were dropped "
            f"(e.g. {df.loc[half, ['Away Team', 'Home Team']].head(3).values.tolist()})"
        )
    dropped = int((~ladder).sum())
    df = df.loc[ladder].copy()

    df["away_score"] = pd.to_numeric(df["Away Score"], errors="coerce")
    df["home_score"] = pd.to_numeric(df["Home Score"], errors="coerce")
    df["game_id"] = (
        df["date"].dt.strftime("%Y-%m-%d") + "|" + df["Away Team"] + "@" + df["Home Team"] + "|" + df["Arena"]
    )
    if "Kraken ID" in df.columns:  # ledger files carry the league's own game id
        kid = df["Kraken ID"].fillna("").astype(str).str.strip()
        df.loc[kid != "", "game_id"] = "K" + kid[kid != ""]
    dup = df["game_id"].duplicated(keep="first")
    if dup.any():
        warnings.append(f"{dup.sum()} duplicate game rows removed: {df.loc[dup, 'game_id'].head(3).tolist()}")
        df = df.loc[~dup]
    df = df.sort_values(["date", "file_row"], kind="stable").reset_index(drop=True)

    cols = {
        "game_id": "game_id",
        "date": "date",
        "Arena": "arena",
        "Game Type": "game_type",
        "Away Team": "away_name",
        "Home Team": "home_name",
        "Away Division": "away_div_label",
        "Home Division": "home_div_label",
        "away_score": "away_score",
        "home_score": "home_score",
        "file_row": "file_row",
    }
    df = df[list(cols)].rename(columns=cols)
    has_score = df["away_score"].notna() & df["home_score"].notna()
    partial = df["away_score"].notna() ^ df["home_score"].notna()
    if partial.any():
        warnings.append(f"{partial.sum()} games with only one score treated as upcoming")
    played = df.loc[has_score].copy()
    played["away_score"] = played["away_score"].astype(int)
    played["home_score"] = played["home_score"].astype(int)
    upcoming = df.loc[~has_score].copy()
    return Schedule(played=played.reset_index(drop=True), upcoming=upcoming.reset_index(drop=True),
                    warnings=warnings, dropped_non_ladder=dropped)


def team_rows(games: pd.DataFrame, id_cols: tuple[str, str] = ("away_id", "home_id")) -> pd.DataFrame:
    """One row per team per game with the team's own division label (for division logic)."""
    games = games.sort_values(["date", "file_row"], kind="stable")
    order = list(range(len(games)))
    away = pd.DataFrame({"team_id": games[id_cols[0]].values, "division_label": games["away_div_label"].values,
                         "order": order, "date": games["date"].values, "opp_id": games[id_cols[1]].values})
    home = pd.DataFrame({"team_id": games[id_cols[1]].values, "division_label": games["home_div_label"].values,
                         "order": order, "date": games["date"].values, "opp_id": games[id_cols[0]].values})
    return pd.concat([away, home], ignore_index=True)
