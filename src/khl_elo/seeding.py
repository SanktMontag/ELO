"""Starting-rating rules shared by `khl season new` and `khl run` (late-appearing teams).

  continuing team (played last season)  R + offseason_regression × (div_mean − R)
  returning after N missed seasons      R + min(1, offseason_regression + hiatus_per_season × N) × (div_mean − R)
  new team                              div_mean (interpolated from neighbouring divisions if empty)
  team split out of a merged team       inherits the merged team's rating if that is more recent
                                        than its own (see data/registry/lineage.csv)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Season, SeasonRules, load_seasons
from .divisions import division_sort_key
from .ingest import clean_name
from .registry import Registry


def season_end_ratings(season: Season, reg: Registry, method: str = "v1") -> pd.DataFrame:
    """End-of-season ratings keyed by team_id: columns team_id, elo, division.

    Pipeline seasons read output/<season>/<method>/ratings.csv (teams with GP > 0).
    Legacy seasons read the frozen legacy ratings and map names through the
    registry; unmapped names are skipped.
    """
    empty = pd.DataFrame(columns=["team_id", "elo", "division"])
    if not season.legacy:
        path = season.output_dir(method) / "ratings.csv"
        if not path.exists():
            return empty
        df = pd.read_csv(path, dtype={"team_id": str, "Div": str})
        if "GP" in df.columns:
            df = df.loc[df["GP"] > 0]
        return pd.DataFrame({"team_id": df["team_id"], "elo": df["ELO"].astype(float), "division": df["Div"]})
    if not season.legacy_ratings or not season.legacy_ratings.exists():
        return empty
    df = pd.read_csv(season.legacy_ratings, dtype={"Div": str})
    ids = df["Team"].map(lambda n: reg.resolve(clean_name(n), season.id))
    out = pd.DataFrame({"team_id": ids, "elo": df["ELO"].astype(float), "division": df["Div"]})
    return out.dropna(subset=["team_id"]).drop_duplicates("team_id")


def last_known(before: Season, reg: Registry, method: str = "v1") -> dict[str, tuple[float, str, Season]]:
    """team_id -> (elo, division, season) from the latest earlier season the team played in."""
    found: dict[str, tuple[float, str, Season]] = {}
    for s in sorted((s for s in load_seasons() if s.index < before.index), key=lambda s: s.index):
        for r in season_end_ratings(s, reg, method).itertuples():
            found[r.team_id] = (float(r.elo), str(r.division), s)
    # Split teams pick up the merged team's rating when it is more recent than their own.
    for link in reg.lineage.itertuples():
        combined = found.get(link.combined_id)
        own = found.get(link.part_id)
        if combined and (own is None or combined[2].index > own[2].index):
            found[link.part_id] = combined
    return found


def division_means(ratings: dict[str, float], divisions: dict[str, str]) -> dict[str, float]:
    keys = [t for t in ratings if divisions.get(t)]
    if not keys:
        return {}
    s = pd.Series({t: ratings[t] for t in keys})
    return s.groupby(pd.Series({t: divisions[t] for t in keys})).mean().to_dict()


def nearest_division_value(div: str, means: dict[str, float]) -> float | None:
    """Mean of `div`, or the average of the neighbouring divisions in ladder order."""
    if div in means:
        return means[div]
    if not means:
        return None
    order = sorted(set(means) | {div}, key=division_sort_key)
    i = order.index(div)
    vals = [means[order[j]] for j in (i - 1, i + 1) if 0 <= j < len(order) and order[j] in means]
    return float(np.mean(vals)) if vals else None


def seed_team(tid: str, div: str, season: Season, history: dict, means: dict[str, float],
              rules: SeasonRules) -> tuple[float, str, float | None, str | None, int | None]:
    """Return (elo, source, prev_elo, prev_season, missed) for one team."""
    target = nearest_division_value(div, means)
    if tid in history:
        elo, _, last = history[tid]
        missed = season.index - last.index - 1
        f = rules.hiatus_fraction(missed)
        new = elo + f * ((target if target is not None else elo) - elo)
        src = (f"continuing, {f:.0%} to div mean" if missed == 0
               else f"returning after {missed} season(s), {f:.0%} to div mean")
        return new, src, elo, last.id, missed
    if target is None:
        raise ValueError(f"No rated teams in or near division {div!r} to seed team {tid}")
    return target, "new team: division mean", None, None, None
