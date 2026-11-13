"""Replay a season's games and write the output tables."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, Season, SeasonRules, get_season
from .divisions import current_divisions, division_sort_key, load_confirmed, parse_label
from .ingest import Schedule, load_schedule, team_rows
from .methods import Method, get_method
from .registry import Registry, Resolution, resolve_names
from .seeding import division_means, last_known, seed_team

TEAM_GAME_COLS = ["Date", "Team", "ELO", "Opponent", "Opp ELO", "Delta", "Win %", "Tie %", "Loss %",
                  "GF", "GA", "Result", "+/- ELO", "ELO Post Game",
                  "Div", "Opp Div", "Side", "Game Type", "game_id", "team_id", "opp_id"]
RESULT = {1.0: "Win", 0.5: "Tie", 0.0: "Loss"}


class UnresolvedNamesError(RuntimeError):
    def __init__(self, unknown: dict[str, list], review_path: Path):
        self.unknown = unknown
        self.review_path = review_path
        super().__init__(
            f"{len(unknown)} team name(s) in the schedule are not in the registry: "
            f"{', '.join(sorted(unknown))}. Run `khl teams resolve <season>` (details in {review_path})."
        )


@dataclass
class ReplayResult:
    team_games: pd.DataFrame
    games: pd.DataFrame
    final: dict[str, float]
    record: dict[str, dict[str, int]] = field(default_factory=dict)


def replay(games: pd.DataFrame, start: dict[str, float], method: Method,
           names: dict[str, str] | None = None, new_ids: set[str] | None = None) -> ReplayResult:
    """Apply `method` to played games in order.

    games: columns date, away_id, home_id, away_score, home_score, game_id,
           away_div_label, home_div_label, game_type (sorted chronologically).
    start: starting rating per id (every id in games must be present).
    """
    names = names or {}
    new_ids = new_ids or set()
    ratings = {k: float(v) for k, v in start.items()}
    gp: dict[str, int] = {}
    record: dict[str, dict[str, int]] = {}
    rows: list[dict] = []
    game_rows: list[dict] = []
    for g in games.itertuples(index=False):
        a, h = g.away_id, g.home_id
        ra, rh = ratings[a], ratings[h]
        ga, gh = int(g.away_score), int(g.home_score)
        u = method.update(ra, rh, ga, gh, {"away_gp": gp.get(a, 0), "home_gp": gp.get(h, 0),
                                           "away_new": a in new_ids, "home_new": h in new_ids})
        ratings[a] = ra + u.away_delta
        ratings[h] = rh + u.home_delta
        sa = method.result(ga, gh)
        for tid, oid, r, ro, probs, gf, gaa, s, d, side, div, odiv in (
            (a, h, ra, rh, u.away_probs, ga, gh, sa, u.away_delta, "Away", g.away_div_label, g.home_div_label),
            (h, a, rh, ra, u.home_probs, gh, ga, 1 - sa, u.home_delta, "Home", g.home_div_label, g.away_div_label),
        ):
            gp[tid] = gp.get(tid, 0) + 1
            rec = record.setdefault(tid, {"W": 0, "L": 0, "T": 0, "GF": 0, "GA": 0})
            rec[{1.0: "W", 0.0: "L", 0.5: "T"}[s]] += 1
            rec["GF"] += gf
            rec["GA"] += gaa
            rows.append({
                "Date": g.date.strftime("%Y-%m-%d"),
                "Team": names.get(tid, tid),
                "ELO": round(r),
                "Opponent": names.get(oid, oid),
                "Opp ELO": round(ro),
                "Delta": round(r - ro),
                "Win %": round(probs[0] * 100, 1),
                "Tie %": round(probs[1] * 100, 1),
                "Loss %": round(probs[2] * 100, 1),
                "GF": gf, "GA": gaa,
                "Result": RESULT[s],
                "+/- ELO": round(d),
                "ELO Post Game": round(r + d),
                "Div": _code(div), "Opp Div": _code(odiv),
                "Side": side, "Game Type": g.game_type,
                "game_id": g.game_id, "team_id": tid, "opp_id": oid,
                # unrounded values for analysis
                "_e": u.away_expected if side == "Away" else 1 - u.away_expected,
                "_s": s,
            })
        game_rows.append({
            "game_id": g.game_id, "Date": g.date.strftime("%Y-%m-%d"), "Game Type": g.game_type,
            "Away": names.get(a, a), "Home": names.get(h, h), "Away Score": ga, "Home Score": gh,
            "Away Div": _code(g.away_div_label), "Home Div": _code(g.home_div_label),
            "Away ELO Prior": round(ra), "Home ELO Prior": round(rh),
            "Away E %": round(u.away_expected * 100, 1),
            "Away Delta": round(u.away_delta), "Home Delta": round(u.home_delta),
            "Away ELO Post": round(ratings[a]), "Home ELO Post": round(ratings[h]),
            "away_id": a, "home_id": h,
        })
    tg = pd.DataFrame(rows, columns=TEAM_GAME_COLS + ["_e", "_s"])
    return ReplayResult(tg, pd.DataFrame(game_rows), ratings, record)


def _code(label: str) -> str:
    p = parse_label(label)
    return p.code if p else str(label)


# ---------------------------------------------------------------- season run

def load_seed(path: Path) -> pd.DataFrame:
    if not path or not path.exists():
        raise FileNotFoundError(f"Seed file {path} not found. Create it with `khl season new` or `khl bootstrap`.")
    df = pd.read_csv(path, dtype={"team_id": str, "division": str})
    need = {"team_id", "elo"}
    if not need <= set(df.columns):
        raise ValueError(f"{path} must have columns {need}")
    if df["team_id"].duplicated().any():
        raise ValueError(f"{path}: duplicate team_id {df.loc[df.team_id.duplicated(), 'team_id'].tolist()}")
    return df


@dataclass
class RunResult:
    season: Season
    method: Method
    out_dir: Path
    ratings: pd.DataFrame
    review: pd.DataFrame
    meta: dict


def prepare(season: Season, reg: Registry) -> tuple[Schedule, dict[str, str], pd.DataFrame, Resolution]:
    """Load schedule, resolve names. Returns (schedule, name->id, review rows, resolution)."""
    sched = load_schedule(season.schedule)
    names = pd.concat([sched.played[["away_name", "home_name"]], sched.upcoming[["away_name", "home_name"]]])
    res = resolve_names(reg, names.values.ravel().tolist(), season.id)
    review = []
    for n, sugg in res.unknown.items():
        review.append({"kind": "unknown_name", "subject": n,
                       "detail": "; ".join(f"{name} ({tid}, {score})" for tid, name, score in sugg) or "no close match"})
    for n, st in res.inactive.items():
        review.append({"kind": "inactive_team_playing", "subject": n,
                       "detail": f"registry status is {st}; it will be set active on run"})
    for w in sched.warnings:
        review.append({"kind": "schedule_warning", "subject": "", "detail": w})
    return sched, res.ids, pd.DataFrame(review, columns=["kind", "subject", "detail"]), res


def run_season(season_id: str, method_name: str = "v1", reg: Registry | None = None,
               write: bool = True) -> RunResult:
    season = get_season(season_id)
    if season.legacy:
        raise ValueError(f"{season_id} is a legacy season; its outputs are frozen under data/legacy.")
    reg = reg or Registry.load()
    method = get_method(method_name)
    out_dir = season.output_dir(method_name)
    out_dir.mkdir(parents=True, exist_ok=True)

    sched, ids, review, res = prepare(season, reg)
    if res.unknown:
        review.to_csv(out_dir / "review.csv", index=False)
        raise UnresolvedNamesError(res.unknown, out_dir / "review.csv")

    played = sched.played.assign(away_id=sched.played["away_name"].map(ids), home_id=sched.played["home_name"].map(ids))
    upcoming = sched.upcoming.assign(away_id=sched.upcoming["away_name"].map(ids), home_id=sched.upcoming["home_name"].map(ids))

    seed = load_seed(season.seed)
    seed_div = dict(zip(seed["team_id"], seed.get("division", pd.Series(dtype=str)).fillna("")))
    start = dict(zip(seed["team_id"], seed["elo"].astype(float)))

    all_games = pd.concat([played, upcoming], ignore_index=True)
    cur_div, div_flags = current_divisions(team_rows(all_games), fallback=seed_div,
                                           confirmed=load_confirmed(season.id))
    for tid, (kind, why) in div_flags.items():
        review.loc[len(review)] = [kind, reg.name_of(tid), why]

    # Teams that appear after the seed file was made (e.g. the export only covered
    # the first weeks): seed them with the same carry-over / hiatus / new-team rules,
    # and append them to the seed file so later runs are stable.
    in_games = set(all_games["away_id"]) | set(all_games["home_id"])
    unseeded = sorted(in_games - set(start))
    added = []
    if unseeded:
        rules = SeasonRules.from_config(method.cfg)
        history = last_known(season, reg, method_name)
        means = division_means(start, {t: seed_div.get(t) or cur_div.get(t) for t in start})
        for tid in unseeded:
            div = cur_div.get(tid, "")
            elo, src, prev, prev_s, missed = seed_team(tid, div, season, history, means, rules)
            added.append({"team_id": tid, "team": reg.name_of(tid), "division": div, "elo": round(elo),
                          "source": f"added on run: {src}", "prev_elo": prev, "prev_season": prev_s,
                          "missed_seasons": missed})
            review.loc[len(review)] = ["auto_seeded", reg.name_of(tid), f"{src}; seed {elo:.0f} ({div})"]
            start[tid] = float(round(elo))

    team_names = {tid: reg.name_of(tid) for tid in set(start) | in_games}
    src = seed["source"].fillna("") if "source" in seed.columns else pd.Series("", index=seed.index)
    new_ids = set(seed.loc[src.str.startswith("new team"), "team_id"]) | set(unseeded)
    rr = replay(played, start, method, team_names, new_ids)

    # ---- ratings table
    finals = []
    for tid, elo in rr.final.items():
        rec = rr.record.get(tid, {"W": 0, "L": 0, "T": 0, "GF": 0, "GA": 0})
        finals.append({
            "team_id": tid, "Team": team_names[tid], "Div": cur_div.get(tid) or seed_div.get(tid, ""),
            "ELO": round(elo) if method.round_final else int(elo),
            "GP": rec["W"] + rec["L"] + rec["T"], "W": rec["W"], "L": rec["L"], "T": rec["T"],
            "GF": rec["GF"], "GA": rec["GA"],
            "Start ELO": round(start[tid]), "Season +/-": round(elo - start[tid]),
            "Status": reg.status_of(tid),
        })
    ratings = pd.DataFrame(finals).sort_values(["ELO", "Team"], ascending=[False, True], kind="stable").reset_index(drop=True)
    ratings.insert(0, "Ranking", ratings.index + 1)

    # ---- division summary
    divs = (ratings.groupby("Div")["ELO"].agg(Teams="size", ELO="mean", StDev="std", Min="min", Max="max")
            .reset_index())
    divs = divs.iloc[sorted(range(len(divs)), key=lambda i: division_sort_key(divs["Div"].iat[i]))].reset_index(drop=True)
    divs[["ELO", "StDev"]] = divs[["ELO", "StDev"]].round(0)
    leaders = ratings.sort_values("ELO", ascending=False).drop_duplicates("Div").set_index("Div")["Team"]
    divs["Leader"] = divs["Div"].map(leaders)

    # ---- predictions for upcoming games
    preds = []
    for g in upcoming.itertuples(index=False):
        ra, rh = rr.final.get(g.away_id, start.get(g.away_id)), rr.final.get(g.home_id, start.get(g.home_id))
        p = method.predict(ra, rh)
        preds.append({"Date": g.date.strftime("%Y-%m-%d"), "Arena": g.arena, "Away": team_names[g.away_id],
                      "Home": team_names[g.home_id], "Away ELO": round(ra), "Home ELO": round(rh),
                      "Away Win %": round(p.away_probs[0] * 100, 1), "Tie %": round(p.away_probs[1] * 100, 1),
                      "Home Win %": round(p.away_probs[2] * 100, 1), "game_id": g.game_id})
    predictions = pd.DataFrame(preds, columns=["Date", "Arena", "Away", "Home", "Away ELO", "Home ELO",
                                               "Away Win %", "Tie %", "Home Win %", "game_id"])

    tg = rr.team_games
    meta = {
        "season": season.id, "season_label": season.label, "method": method.name,
        "method_description": method.description, "params": method.cfg, "params_hash": method.params_hash(),
        "schedule_file": season.schedule.relative_to(ROOT).as_posix() if season.schedule else None,
        "schedule_sha256": _sha(season.schedule), "seed_sha256": _sha(season.seed),
        "games_played": int(len(played)), "games_upcoming": int(len(upcoming)),
        "first_game": played["date"].min().strftime("%Y-%m-%d") if len(played) else None,
        "last_game": played["date"].max().strftime("%Y-%m-%d") if len(played) else None,
        "away_net_elo": float(tg.loc[tg["Side"] == "Away", "+/- ELO"].sum()) if len(tg) else 0.0,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    if write:
        if added:
            pd.concat([seed, pd.DataFrame(added)], ignore_index=True).to_csv(season.seed, index=False)
        tg.drop(columns=["_e", "_s"]).to_csv(out_dir / "team_games.csv", index=False)
        rr.games.to_csv(out_dir / "games.csv", index=False)
        ratings.to_csv(out_dir / "ratings.csv", index=False)
        divs.to_csv(out_dir / "divisions.csv", index=False)
        predictions.to_csv(out_dir / "predictions.csv", index=False)
        review.to_csv(out_dir / "review.csv", index=False)
        (out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2))
        # Teams that play are active by definition.
        changed = False
        for tid in in_games:
            if reg.status_of(tid) != "active":
                reg.set_status(tid, "active", season.id, "appeared in schedule")
                changed = True
        if changed:
            reg.save()

    return RunResult(season, method, out_dir, ratings, review, meta)


def _sha(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
