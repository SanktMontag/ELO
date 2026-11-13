"""Replay seasons with candidate parameters and score the pre-game predictions.

Works on legacy seasons too: games and seeds are matched by (cleaned) team name,
using each season's own legacy seed file, so no registry is needed.

Metrics (lower is better unless noted):
  es_brier   mean (S - E)^2 on the expected score
  logloss    3-way log loss of the Win/Tie/Loss probabilities
  tie_pred   mean predicted tie probability   (compare with tie_actual)
  away_net   total ELO gained by away teams    (should be ~0)
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

from .config import Season, load_method_config, load_seasons
from .engine import replay
from .ingest import clean_name, load_schedule
from .methods import REGISTRY


def season_games(season: Season) -> tuple[pd.DataFrame, dict[str, float], int]:
    seed_path = season.legacy_seed
    if seed_path is None or not seed_path.exists():
        raise FileNotFoundError(f"{season.id}: no legacy_seed to backtest from")
    seed = pd.read_csv(seed_path)
    start = dict(zip(seed["Team"].map(clean_name), seed["ELO"].astype(float)))
    played = load_schedule(season.schedule).played
    played = played.assign(away_id=played["away_name"], home_id=played["home_name"])
    known = played["away_id"].isin(start) & played["home_id"].isin(start)
    return played.loc[known].reset_index(drop=True), start, int((~known).sum())


def score(team_games: pd.DataFrame, method) -> dict:
    away = team_games.loc[team_games["Side"] == "Away"]
    e, s = away["_e"].to_numpy(), away["_s"].to_numpy()
    probs = np.array([method.outcome_probs(x) for x in e])
    idx = np.where(s == 1.0, 0, np.where(s == 0.5, 1, 2))
    p = np.clip(probs[np.arange(len(idx)), idx], 1e-9, 1)
    return {
        "games": len(away),
        "es_brier": float(np.mean((s - e) ** 2)),
        "logloss": float(-np.mean(np.log(p))),
        "tie_actual": float(np.mean(s == 0.5)),
        "tie_pred": float(np.mean(probs[:, 1])),
        "away_net": float(away["+/- ELO"].sum()),
    }


def calibration(team_games: pd.DataFrame) -> pd.DataFrame:
    """Favourite's predicted expected score vs actual score, by bin."""
    away = team_games.loc[team_games["Side"] == "Away"]
    e, s = away["_e"].to_numpy(), away["_s"].to_numpy()
    flip = e < 0.5
    e, s = np.where(flip, 1 - e, e), np.where(flip, 1 - s, s)
    df = pd.DataFrame({"e": e, "s": s})
    df["bin"] = pd.cut(df["e"], [0.5, 0.6, 0.7, 0.8, 0.9, 1.0], include_lowest=True)
    return df.groupby("bin", observed=True).agg(n=("s", "size"), predicted=("e", "mean"), actual=("s", "mean")).round(3)


def evaluate(method_name: str, overrides: dict, seasons: list[Season]) -> tuple[dict, pd.DataFrame]:
    cfg = {**load_method_config(method_name), **overrides}
    method = REGISTRY[method_name](cfg)
    frames = []
    for s in seasons:
        games, start, _ = season_games(s)
        frames.append(replay(games, start, method).team_games.assign(season=s.id))
    tg = pd.concat(frames, ignore_index=True)
    return score(tg, method), tg


def fit_draw_factor(team_games: pd.DataFrame, method_name: str) -> float:
    """Draw factor minimising 3-way log loss (does not affect ratings)."""
    best = (math.inf, None)
    for d in np.arange(0.30, 0.96, 0.01):
        m = REGISTRY[method_name]({**load_method_config(method_name), "draw_factor": float(d)})
        ll = score(team_games, m)["logloss"]
        if ll < best[0]:
            best = (ll, round(float(d), 2))
    return best[1]


def grid_search(method_name: str, seasons: list[Season], ks: list[float], scales: list[float]) -> pd.DataFrame:
    rows = []
    for k, sc in itertools.product(ks, scales):
        sc_res, _ = evaluate(method_name, {"k": k, "scale": sc}, seasons)
        rows.append({"k": k, "scale": sc, **sc_res})
    return pd.DataFrame(rows).sort_values("es_brier").reset_index(drop=True)


def chained(method_name: str, regression: float, reg, overrides: dict | None = None) -> tuple[dict, pd.DataFrame]:
    """Carry ratings across season boundaries instead of using each season's hand-made seeds.

    The first season starts from its legacy seed. Each later season starts from the previous
    season's v1 end ratings, regressed by `regression` toward the mean of the division the team
    is listed in for the new season. Teams without a previous rating keep their hand-made seed.
    Only the carried seasons are scored.
    """
    cfg = {**load_method_config(method_name), **(overrides or {})}
    method = REGISTRY[method_name](cfg)
    seasons = backtest_seasons()
    prev_end: dict[str, float] = {}
    frames = []
    for i, s in enumerate(seasons):
        games, hand, _ = season_games(s)
        seed = pd.read_csv(s.legacy_seed, dtype={"Div": str})
        div = dict(zip(seed["Team"].map(clean_name), seed["Div"]))

        def ident(name, sid=s.id):
            return reg.resolve(name, sid) or name

        start = dict(hand)
        if i > 0:
            carried = {n: prev_end[ident(n)] for n in hand if ident(n) in prev_end}
            means = pd.Series(carried).groupby(pd.Series({n: div[n] for n in carried})).mean().to_dict()
            for n, r in carried.items():
                start[n] = r + regression * (means[div[n]] - r)
        rr = replay(games, start, method)
        if i > 0:
            frames.append(rr.team_games.assign(season=s.id))
        prev_end = {ident(n): v for n, v in rr.final.items()}
    tg = pd.concat(frames, ignore_index=True)
    return score(tg, method), tg


def backtest_seasons(ids: list[str] | None = None) -> list[Season]:
    all_s = [s for s in load_seasons() if s.legacy_seed is not None]
    return [s for s in all_s if not ids or s.id in ids]
