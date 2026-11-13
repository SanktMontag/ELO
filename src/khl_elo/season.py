"""Season roll-over (`khl season new`) and the one-time Fall 2026 bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import DATA_DIR, SeasonRules, get_season, load_method_config
from .divisions import current_divisions, load_confirmed
from .engine import prepare
from .ingest import clean_name, team_rows
from .registry import Registry
from .seeding import division_means, last_known, seed_team

SEED_COLS = ["team_id", "team", "division", "elo", "source", "prev_elo", "prev_season", "missed_seasons"]


# ------------------------------------------------------------------ new season

@dataclass
class NewSeasonReport:
    seeds: pd.DataFrame
    review: pd.DataFrame
    not_scheduled: list[str]


def new_season(season_id: str, method: str = "v1", reg: Registry | None = None,
               force: bool = False, write: bool = True) -> NewSeasonReport:
    """Write data/seeds/<season>.csv for every team in the new season's schedule.

    Teams that first appear later in the season are seeded by `khl run` with the
    same rules. Hiatus is not set here (early exports are partial); use
    `khl season close <previous season>` once a season is complete.
    """
    season = get_season(season_id)
    if season.legacy:
        raise ValueError("Cannot create seeds for a legacy season")
    if season.seed is None:
        raise ValueError(f"Season {season_id} has no `seed` path in seasons.toml")
    if season.seed.exists() and not force:
        raise FileExistsError(f"{season.seed} already exists; pass --force to overwrite")
    reg = reg or Registry.load()
    rules = SeasonRules.from_config(load_method_config(method))

    sched, ids, review, res = prepare(season, reg)
    if res.unknown:
        raise RuntimeError(
            f"Unresolved team names: {', '.join(sorted(res.unknown))}. Run `khl teams resolve {season_id}` first."
        )
    all_games = pd.concat([sched.played, sched.upcoming], ignore_index=True)
    all_games["away_id"] = all_games["away_name"].map(ids)
    all_games["home_id"] = all_games["home_name"].map(ids)
    playing = set(all_games["away_id"]) | set(all_games["home_id"])

    history = last_known(season, reg, method)
    prev_div = {t: v[1] for t, v in history.items()}
    cur_div, flags = current_divisions(team_rows(all_games), fallback=prev_div,
                                       confirmed=load_confirmed(season.id))
    for tid, (kind, why) in flags.items():
        review.loc[len(review)] = [kind, reg.name_of(tid), why]

    # Division means from teams carrying a rating into their *new* division.
    carried = {t: history[t][0] for t in playing if t in history}
    means = division_means(carried, {t: cur_div[t] for t in carried})

    rows = []
    for tid in sorted(playing, key=reg.name_of):
        div = cur_div.get(tid, "")
        elo, src, prev, prev_s, missed = seed_team(tid, div, season, history, means, rules)
        rows.append([tid, reg.name_of(tid), div, round(elo), src,
                     None if prev is None else round(prev), prev_s, missed])
    seeds = pd.DataFrame(rows, columns=SEED_COLS)

    for tid in playing:
        if reg.status_of(tid) != "active":
            reg.set_status(tid, "active", season.id, "in new season schedule")
    not_scheduled = sorted(reg.name_of(t) for t in reg.teams["team_id"]
                           if t not in playing and reg.status_of(t) == "active")

    if write:
        season.seed.parent.mkdir(parents=True, exist_ok=True)
        seeds.to_csv(season.seed, index=False)
        reg.save()
    return NewSeasonReport(seeds, review, not_scheduled)


def close_season(season_id: str, method: str = "v1", reg: Registry | None = None,
                 write: bool = True) -> list[str]:
    """After a season is complete: mark active teams that played no games in it as hiatus."""
    season = get_season(season_id)
    reg = reg or Registry.load()
    path = season.output_dir(method) / "ratings.csv"
    if not path.exists():
        raise FileNotFoundError(f"Run `khl run {season_id}` first ({path} missing)")
    df = pd.read_csv(path, dtype={"team_id": str})
    played = set(df.loc[df["GP"] > 0, "team_id"])
    marked = []
    for tid in list(reg.teams["team_id"]):
        if tid not in played and reg.status_of(tid) == "active":
            reg.set_status(tid, "hiatus", season.id, "no games this season")
            marked.append(reg.name_of(tid))
    if write and marked:
        reg.save()
    return marked


# ------------------------------------------------------------------ bootstrap

# Summer 2026 -> Fall 2026 renames confirmed by matching division + rating.
KNOWN_RENAMES = {
    "Monarchs 6": "Monarchs 6B",
    "Not Sure 6": "Not Sure 6D",
    "Rainier Reindeer HC-6": "Rainier Reindeer HC-6B",
    "Rainier Reindeers HC-9": "Rainier Reindeers HC-9A",
    "Spicy Kittens HC-8": "Spicy Kittens HC-8A",
    "Spicy Kittens HC-9": "Spicy Kittens HC-9B",
    "The Seals": "Seals",
    "WKUTP-5": "WKUTP-4",
}


def bootstrap(force: bool = False) -> dict:
    """Create the registry and Fall 2026 seeds from the legacy initial_26_Fall.csv."""
    reg_dir = DATA_DIR / "registry"
    if (reg_dir / "teams.csv").exists() and not force:
        raise FileExistsError("Registry already exists; pass --force to rebuild it from scratch")
    fall = get_season("2026-fall")
    summer = get_season("2026-summer")

    reg = Registry(pd.DataFrame(columns=["team_id", "name", "status", "first_season", "notes"]),
                   pd.DataFrame(columns=["alias", "team_id", "from_season", "to_season"]),
                   pd.DataFrame(columns=["date", "season", "team_id", "event", "detail"]), reg_dir)

    init = pd.read_csv(fall.legacy_seed, dtype={"Div": str}).sort_values("Ranking", kind="stable")
    raw_names = init["Team"].copy()
    init["Team"] = init["Team"].map(clean_name)
    review = []
    # Names that differ only by whitespace/case (e.g. "Flying Monkeys " vs "Flying Monkeys")
    # are one team in the registry; keep the higher-ranked seed and flag the rest.
    dup = init["Team"].str.casefold().duplicated(keep="first")
    for i in init.index[dup]:
        review.append({"team_id": "", "summer_name": "", "summer_div": "", "summer_elo": "",
                       "possible_fall_match": f"MERGED: initial_26_Fall rows {raw_names[i]!r} ({init.at[i, 'Div']}, "
                                              f"{init.at[i, 'ELO']}) collapsed into {init.at[i, 'Team']!r}; kept higher seed"})
    init = init.loc[~dup]
    for r in init.itertuples():
        tid = reg.next_id()
        reg.teams.loc[len(reg.teams)] = [tid, r.Team, "active", fall.id, ""]
        reg.add_alias(tid, r.Team)  # open-ended: also matches this name in legacy seasons
        reg.log(fall.id, tid, "bootstrap", f"seeded from initial_26_Fall.csv ({r.Div}, {r.ELO})")

    for old, new in KNOWN_RENAMES.items():
        tid = reg.resolve(new)
        if tid:
            reg.add_alias(tid, old, to_season=summer.id)
            reg.log(fall.id, tid, "rename", f"{old} -> {new} (bootstrap)")

    # Summer teams that did not return for Fall: register as on hiatus so a later
    # return can pick up their last rating.
    summer_r = pd.read_csv(summer.legacy_ratings, dtype={"Div": str})
    for r in summer_r.itertuples():
        name = clean_name(r.Team)
        if reg.resolve(name, summer.id):
            continue
        sugg = reg.suggest(name)
        tid = reg.next_id()
        reg.teams.loc[len(reg.teams)] = [tid, name, "hiatus", summer.id, "summer 2026 team not in fall 2026"]
        reg.add_alias(tid, name)
        reg.log(fall.id, tid, "hiatus", "did not appear in Fall 2026 schedule (bootstrap)")
        review.append({"team_id": tid, "summer_name": name, "summer_div": r.Div, "summer_elo": r.ELO,
                       "possible_fall_match": "; ".join(f"{n} ({t}, {s})" for t, n, s in sugg)})

    seeds = init.assign(team_id=init["Team"].map(lambda n: reg.resolve(n, fall.id)))
    seeds = pd.DataFrame({
        "team_id": seeds["team_id"], "team": seeds["Team"], "division": seeds["Div"], "elo": seeds["ELO"],
        "source": "legacy initial_26_Fall.csv", "prev_elo": None, "prev_season": None, "missed_seasons": None,
    })
    reg.save()
    fall.seed.parent.mkdir(parents=True, exist_ok=True)
    seeds.to_csv(fall.seed, index=False)
    review_df = pd.DataFrame(review)
    review_df.to_csv(reg_dir / "bootstrap_review.csv", index=False)
    return {"teams": len(reg.teams), "aliases": len(reg.aliases), "seeds": len(seeds),
            "hiatus": len(review), "review_file": reg_dir / "bootstrap_review.csv", "review": review_df}
