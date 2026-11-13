"""`khl` command line.

  khl bootstrap                         one-time: registry + Fall 2026 seeds from legacy files
  khl import   <season> <export.csv>    merge a Kraken export into the season (add/update games)
  khl ingest   <season>                 check a schedule export (unknown names, division issues)
  khl divisions list|confirm <season>   review / confirm ambiguous division labels (e.g. bare "Division 3")
  khl divisions set <season> <team> <div>   pin a team's division until its latest label changes
  khl run      <season> [--method v1]   compute ratings and write output/<season>/<method>/
  khl season new <season> [--force]     build next season's seeds (carry-over, hiatus, new teams)
  khl season close <season>             season finished: teams with no games -> hiatus
  khl teams list [--status S]
  khl teams resolve <season>            interactively map unknown schedule names
  khl teams add <name> --season S
  khl teams alias <team> <name> [--from S] [--to S]
  khl teams rename <team> <new name> --season S
  khl teams merge <from> <into> --season S
  khl teams hiatus|dissolve|activate <team> --season S
  khl teams history <team>
  khl teams link <combined team> --parts <team> <team> --season S   (mergers / splits)
  khl backtest [--seasons ...] [--method v1] [--grid] [--chained]

<team> may be a team_id (T0042) or any current/former name.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from .config import get_season
from .registry import Registry

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)


def _print_df(df: pd.DataFrame, max_rows: int = 200) -> None:
    if df.empty:
        print("  (none)")
    else:
        print(df.to_string(index=False, max_rows=max_rows))


# ------------------------------------------------------------------ commands

def cmd_bootstrap(a):
    from .season import bootstrap

    info = bootstrap(force=a.force)
    print(f"Registry: {info['teams']} teams, {info['aliases']} aliases. Seeds: {info['seeds']} teams.")
    print(f"{info['hiatus']} Summer 2026 teams not in Fall 2026 registered as hiatus.")
    print(f"Review possible renames in {info['review_file']}:")
    _print_df(info["review"])


def cmd_import(a):
    from pathlib import Path

    from .importer import import_export

    rep = import_export(a.season, Path(a.file), prune=not a.no_prune, dry_run=a.dry_run)
    lo, hi = rep.window or ("-", "-")
    print(f"{'DRY RUN - nothing written. ' if a.dry_run else ''}Export covers {lo} to {hi}.")

    def section(title, items, limit=15):
        if items:
            print(f"\n{title} ({len(items)}):")
            for x in items[:limit]:
                print(f"  {x}")
            if len(items) > limit:
                print(f"  ... and {len(items) - limit} more")

    section("New games", rep.added)
    section("Scores added", rep.scored)
    section("Scores corrected", rep.corrected)
    section("Rescheduled", rep.rescheduled)
    section("Removed (unplayed, no longer in export)", rep.pruned)
    section("Warnings", rep.warnings, limit=50)
    print(f"\n{rep.unchanged} unchanged, {rep.detail_updates} with time/arena/division updates. "
          f"Season ledger now has {rep.ledger_games} games (all leagues).")
    if rep.backup:
        print(f"Export archived to {rep.backup}")
    if a.dry_run or not rep.changed:
        return 0
    print("\n--- checking names and divisions")
    code = cmd_ingest(argparse.Namespace(season=a.season))
    if code:
        return code
    _offer_division_confirm(a.season)
    if a.run:
        print("\n--- running ratings")
        return cmd_run(argparse.Namespace(season=a.season, method="v1"))
    print(f"\nNext: khl run {a.season}")
    return 0


def _offer_division_confirm(season_id: str) -> None:
    """After an import: offer to confirm ambiguous divisions right away (interactive terminals only)."""
    if not sys.stdin.isatty():
        return
    season = get_season(season_id)
    reg = Registry.load()
    picks, fallback, _, _, _ = _division_picks(season, reg)
    if not picks or not any(p.source == "unconfirmed" for p in picks.values()):
        return
    try:
        ans = input("\nConfirm ambiguous divisions now? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if ans in ("", "y", "yes"):
        print()
        _confirm_divisions(season, reg, picks, fallback)


def _division_picks(season, reg: Registry):
    """(picks, seed divisions, schedule, review, name resolution); picks is None if names are unresolved."""
    from .divisions import load_confirmed, resolve_divisions
    from .engine import load_seed, prepare
    from .ingest import team_rows

    sched, ids, review, res = prepare(season, reg)
    fallback: dict[str, str] = {}
    if season.seed and season.seed.exists():
        sd = load_seed(season.seed)
        fallback = dict(zip(sd["team_id"], sd.get("division", pd.Series(dtype=str)).fillna("")))
    if res.unknown:
        return None, fallback, sched, review, res
    g = pd.concat([sched.played, sched.upcoming], ignore_index=True)
    g = g.assign(away_id=g["away_name"].map(ids), home_id=g["home_name"].map(ids))
    picks = resolve_divisions(team_rows(g), fallback, load_confirmed(season.id))
    return picks, fallback, sched, review, res


def cmd_ingest(a):
    from .divisions import pick_flags

    season = get_season(a.season)
    reg = Registry.load()
    picks, fallback, sched, review, res = _division_picks(season, reg)
    print(f"{season.schedule.name}: {len(sched.played)} played, {len(sched.upcoming)} upcoming ladder games "
          f"({sched.dropped_non_ladder} non-ladder rows ignored)")
    if len(sched.played):
        print(f"Last played game: {sched.played['date'].max():%Y-%m-%d}")
    unconfirmed = 0
    if picks is not None:
        for tid, (kind, why) in pick_flags(picks).items():
            review.loc[len(review)] = [kind, reg.name_of(tid), why]
            unconfirmed += kind == "division_unconfirmed"
        for t, p in picks.items():
            old = fallback.get(t)
            if old and old != p.division:
                review.loc[len(review)] = ["division_change", reg.name_of(t), f"{old} -> {p.division}"]
    print("\nReview items:")
    _print_df(review)
    if res.unknown:
        print(f"\n{len(res.unknown)} unknown name(s). Run: khl teams resolve {a.season}")
        return 2
    if unconfirmed:
        print(f"\n{unconfirmed} ambiguous division(s) need confirming. Run: khl divisions confirm {a.season}")
    return 0


def cmd_divisions(a):
    from .divisions import confirm_path, load_confirmed, save_confirmation

    season = get_season(a.season)
    reg = Registry.load()
    if a.action == "clear":
        tid = reg.find(a.team)
        path = confirm_path(season.id)
        if tid not in load_confirmed(season.id):
            print(f"No confirmed division for {reg.name_of(tid)}.")
            return 0
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df.loc[df["team_id"] != tid].to_csv(path, index=False)
        print(f"Cleared confirmed division for {reg.name_of(tid)}.")
        return 0
    picks, fallback, _, _, res = _division_picks(season, reg)
    if picks is None:
        print(f"{len(res.unknown)} unknown name(s). Run: khl teams resolve {a.season}")
        return 2
    if a.action == "list":
        rows = [{"Team": reg.name_of(t), "Division": p.division, "Latest label": p.latest,
                 "Source": p.source, "Previous": fallback.get(t, "")}
                for t, p in picks.items() if a.all or p.source != "label"]
        df = pd.DataFrame(rows, columns=["Team", "Division", "Latest label", "Source", "Previous"])
        _print_df(df.sort_values(["Source", "Team"]) if len(df) else df)
        if not a.all:
            print("\n(teams whose division comes straight from their latest label are hidden; --all shows them)")
        return 0
    if a.action == "set":
        tid = reg.find(a.team)
        p = picks.get(tid)
        if p is None or not p.latest:
            print(f"{reg.name_of(tid)} has no ladder games in {season.id}.")
            return 1
        save_confirmation(season.id, tid, reg.name_of(tid), p.latest, a.division.upper())
        print(f"{reg.name_of(tid)}: {a.division.upper()} (holds while its latest label stays 'Division {p.latest}')")
        return 0
    return _confirm_divisions(season, reg, picks, fallback, include_confirmed=a.all)


def _confirm_divisions(season, reg: Registry, picks, fallback, include_confirmed: bool = False) -> int:
    from .divisions import save_confirmation

    todo = [p for p in picks.values()
            if p.source == "unconfirmed" or (include_confirmed and p.source == "confirmed")]
    if not todo:
        print("No ambiguous divisions to confirm.")
        return 0
    todo.sort(key=lambda p: (p.latest, reg.name_of(p.team_id)))
    print(f"{len(todo)} team(s) whose latest label doesn't say which division they are in.\n"
          "Answers are saved and reused until a later export gives the team a different label.\n")

    def fmt_date(d):
        return f"{d:%m-%d}" if hasattr(d, "strftime") else "?"

    for n, p in enumerate(todo, 1):
        name = reg.name_of(p.team_id)
        cands = p.candidates or sorted({c for c in [p.division, fallback.get(p.team_id, "")] if c})
        print(f"[{n}/{len(todo)}] {name}: latest label 'Division {p.latest}'")
        print("  labels this season: " + ", ".join(
            f"{code} x{cnt} ({fmt_date(d0)}..{fmt_date(d1)})" for code, cnt, d0, d1 in p.history))
        print(f"  previous division: {fallback.get(p.team_id) or '-'}")
        seen, opp_txt = set(), []
        for o in p.recent_opponents:
            if o in seen or len(opp_txt) >= 8:
                continue
            seen.add(o)
            op = picks.get(o)
            tag = "" if op is None else op.division + ("?" if op.source == "unconfirmed" else "")
            opp_txt.append(f"{reg.name_of(o)} ({tag})")
        if opp_txt:
            print(f"  recent opponents under this label: {', '.join(opp_txt)}   (? = also unconfirmed)")
        if p.source == "confirmed":
            print(f"  currently confirmed as {p.division}")
        default = p.division if p.division in cands else None
        opts = "   ".join(f"[{i}] {c}{' (default)' if c == default else ''}" for i, c in enumerate(cands, 1))
        print(f"  {opts}   [k] keep '{p.latest}' as-is   [t] type a division   [s] skip   [q] quit")
        while True:
            try:
                ans = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "q"
            if ans == "q":
                print("\nStopped; answers so far are saved.")
                return 1
            if ans == "s":
                print()
                break
            if ans == "" and default:
                div = default
            elif ans.isdigit() and 1 <= int(ans) <= len(cands):
                div = cands[int(ans) - 1]
            elif ans == "k":
                div = p.latest
            elif ans == "t":
                div = input("  division code (e.g. 3A, 10A-B): ").strip().upper()
                if not div:
                    continue
            else:
                continue
            save_confirmation(season.id, p.team_id, name, p.latest, div)
            print(f"  {name} -> {div}\n")
            break
    return 0


def cmd_run(a):
    from .engine import UnresolvedNamesError, run_season

    try:
        r = run_season(a.season, a.method)
    except UnresolvedNamesError as e:
        print(e)
        return 2
    m = r.meta
    print(f"{m['season_label']} [{m['method']}] {m['games_played']} games through {m['last_game']}, "
          f"{m['games_upcoming']} upcoming. Away net ELO: {m['away_net_elo']:+.0f}")
    print(f"Wrote {r.out_dir}")
    if len(r.review):
        print("\nReview items:")
        _print_df(r.review)
    print("\nTop 10:")
    _print_df(r.ratings.head(10)[["Ranking", "Team", "Div", "ELO", "GP", "W", "L", "T", "Season +/-"]])
    return 0


def cmd_season_new(a):
    from .season import new_season

    rep = new_season(a.season, a.method, force=a.force)
    print(f"Wrote seeds for {len(rep.seeds)} teams to {get_season(a.season).seed}")
    print(rep.seeds["source"].str.replace(r"returning after \d+.*", "returning from hiatus", regex=True)
          .value_counts().to_string())
    if rep.not_scheduled:
        print(f"\nActive teams not (yet) in this schedule ({len(rep.not_scheduled)}); "
              f"they will be seeded automatically if they appear later:\n  {', '.join(rep.not_scheduled)}")
    if len(rep.review):
        print("\nReview items:")
        _print_df(rep.review)
    print("\nEdit the seed file to override any value, then: khl run", a.season)
    return 0


def cmd_season_close(a):
    from .season import close_season

    marked = close_season(a.season, a.method)
    print(f"Marked {len(marked)} team(s) as hiatus (no games in {a.season}): {', '.join(marked) or '-'}")
    return 0


def cmd_teams(a):
    reg = Registry.load()
    act = a.action
    if act == "list":
        t = reg.teams if not a.status else reg.teams.loc[reg.teams["status"] == a.status]
        _print_df(t, max_rows=1000)
        return 0
    if act == "history":
        tid = reg.find(a.team)
        print(reg.teams.loc[reg.teams["team_id"] == tid].to_string(index=False))
        print("\nNames:")
        _print_df(reg.aliases.loc[reg.aliases["team_id"] == tid])
        rel = reg.related(tid)
        if len(rel):
            print("\nLineage:")
            _print_df(rel.assign(combined=rel["combined_id"].map(reg.name_of), part=rel["part_id"].map(reg.name_of)))
        print("\nEvents:")
        _print_df(reg.events.loc[reg.events["team_id"] == tid])
        return 0
    if act == "link":
        combined = reg.find(a.team)
        parts = [reg.find(p) for p in a.parts]
        reg.link(combined, parts, a.season, a.note or "")
        print(f"{reg.name_of(combined)} ({combined}) linked to: " + ", ".join(f"{reg.name_of(p)} ({p})" for p in parts))
    if act == "resolve":
        return _resolve_interactive(reg, a.season)
    if act == "add":
        tid = reg.add_team(a.team, a.season, notes=a.note or "")
        print(f"Added {tid}: {a.team}")
    elif act == "alias":
        tid = reg.find(a.team)
        reg.add_alias(tid, a.name, getattr(a, "from_season", "") or "", a.to or "")
        reg.log(a.from_season or "", tid, "alias", a.name)
        print(f"{a.name!r} -> {tid} ({reg.name_of(tid)})")
    elif act == "rename":
        tid = reg.find(a.team)
        reg.rename(tid, a.name, a.season)
        print(f"{tid} renamed to {a.name!r}; old names kept as aliases")
    elif act == "merge":
        f, t = reg.find(a.team), reg.find(a.name)
        reg.merge(f, t, a.season)
        print(f"Merged {f} into {t} ({reg.name_of(t)}). Re-run affected seasons.")
    elif act in ("hiatus", "dissolve", "activate"):
        tid = reg.find(a.team)
        reg.set_status(tid, {"hiatus": "hiatus", "dissolve": "dissolved", "activate": "active"}[act], a.season, a.note or "")
        print(f"{tid} ({reg.name_of(tid)}) is now {reg.status_of(tid)}")
    reg.save()
    return 0


def _resolve_interactive(reg: Registry, season_id: str) -> int:
    from .engine import prepare

    season = get_season(season_id)
    _, _, _, res = prepare(season, reg)
    if not res.unknown:
        print("All schedule names are known.")
        return 0
    print(f"{len(res.unknown)} unknown name(s) in {season.schedule.name}.\n")
    for name, sugg in res.unknown.items():
        print(f"'{name}'")
        for i, (tid, n, s) in enumerate(sugg, 1):
            print(f"  [{i}] same team as {n} ({tid}, status {reg.status_of(tid)}, similarity {s})")
        print("  [n] new team    [t] type a team name/id    [s] skip    [q] quit")
        while True:
            try:
                ans = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "q"
            if ans == "q":
                reg.save()
                print("\nStopped; answers so far are saved.")
                return 1
            if ans.isdigit() and 1 <= int(ans) <= len(sugg):
                tid = sugg[int(ans) - 1][0]
            elif ans == "t":
                try:
                    tid = reg.find(input("  team name or id: ").strip())
                except KeyError as e:
                    print(f"  {e}")
                    continue
            elif ans == "n":
                tid = reg.add_team(name, season.id)
                print(f"  added {tid}\n")
                break
            elif ans == "s":
                print()
                break
            else:
                continue
            rename = input(f"  Make '{name}' the current name of {reg.name_of(tid)}? [Y/n] ").strip().lower() != "n"
            if rename:
                reg.rename(tid, name, season.id)
            else:
                reg.add_alias(tid, name, from_season=season.id)
                reg.log(season.id, tid, "alias", name)
            print(f"  '{name}' -> {tid}\n")
            break
        reg.save()
    return 0


def cmd_backtest(a):
    from . import backtest as bt

    seasons = bt.backtest_seasons(a.seasons)
    print("Seasons:", ", ".join(s.id for s in seasons))
    for name in a.method:
        res, tg = bt.evaluate(name, {}, seasons)
        print(f"\n== {name} (current config)")
        print(pd.Series(res).round(4).to_string())
        print("\nCalibration (favourite expected score vs actual):")
        print(bt.calibration(tg).to_string())
        if name != "legacy-v0":
            print(f"\nBest-fit draw_factor: {bt.fit_draw_factor(tg, name)}")
    if a.chained:
        reg = Registry.load()
        rows = []
        for r in [float(x) for x in a.regression.split(",")]:
            res, _ = bt.chained(a.method[-1], r, reg)
            rows.append({"regression": r, **res})
        print(f"\n== chained seasons, carry-over regression ({a.method[-1]}); first season not scored")
        print(pd.DataFrame(rows).round(4).to_string(index=False))
    if a.grid:
        ks = [float(x) for x in a.k.split(",")]
        scales = [float(x) for x in a.scale.split(",")]
        print(f"\n== grid search ({a.method[-1]})")
        print(bt.grid_search(a.method[-1], seasons, ks, scales).round(4).to_string(index=False))
    return 0


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="khl", description="KHL ELO pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bootstrap", help="one-time: build registry + Fall 2026 seeds")
    b.add_argument("--force", action="store_true")
    b.set_defaults(fn=cmd_bootstrap)

    im = sub.add_parser("import", help="merge a Kraken export (any date range) into a season")
    im.add_argument("season")
    im.add_argument("file", help="path to the exported CSV, e.g. Downloads/schedule_export(15).csv")
    im.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    im.add_argument("--no-prune", action="store_true",
                    help="keep unplayed games that the export no longer lists (e.g. a division-filtered export)")
    im.add_argument("--run", action="store_true", help="also recompute ratings if the import succeeds")
    im.set_defaults(fn=cmd_import)

    i = sub.add_parser("ingest", help="check a schedule export")
    i.add_argument("season")
    i.set_defaults(fn=cmd_ingest)

    r = sub.add_parser("run", help="compute a season")
    r.add_argument("season")
    r.add_argument("--method", default="v1")
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("season", help="season lifecycle")
    ssub = s.add_subparsers(dest="season_cmd", required=True)
    sn = ssub.add_parser("new", help="build seeds for a new season")
    sn.add_argument("season")
    sn.add_argument("--method", default="v1")
    sn.add_argument("--force", action="store_true")
    sn.set_defaults(fn=cmd_season_new)
    sc = ssub.add_parser("close", help="after a season ends: mark teams with no games as hiatus")
    sc.add_argument("season")
    sc.add_argument("--method", default="v1")
    sc.set_defaults(fn=cmd_season_close)

    d = sub.add_parser("divisions", help="current divisions; confirm ambiguous ones")
    dsub = d.add_subparsers(dest="action", required=True)
    dl = dsub.add_parser("list", help="teams whose division is confirmed, unconfirmed or a fallback")
    dl.add_argument("season")
    dl.add_argument("--all", action="store_true", help="show every team")
    dc = dsub.add_parser("confirm", help="interactively pick divisions for ambiguous labels (e.g. 'Division 3')")
    dc.add_argument("season")
    dc.add_argument("--all", action="store_true", help="also revisit already confirmed teams")
    ds = dsub.add_parser("set", help="set a team's division (holds until its latest label changes)")
    ds.add_argument("season")
    ds.add_argument("team")
    ds.add_argument("division")
    dx = dsub.add_parser("clear", help="forget a team's confirmed division")
    dx.add_argument("season")
    dx.add_argument("team")
    d.set_defaults(fn=cmd_divisions)

    t = sub.add_parser("teams", help="team registry")
    tsub = t.add_subparsers(dest="action", required=True)
    tl = tsub.add_parser("list")
    tl.add_argument("--status", choices=["active", "hiatus", "dissolved"])
    th = tsub.add_parser("history")
    th.add_argument("team")
    tr = tsub.add_parser("resolve")
    tr.add_argument("season")
    ta = tsub.add_parser("add")
    ta.add_argument("team")
    ta.add_argument("--season", required=True)
    ta.add_argument("--note")
    tal = tsub.add_parser("alias")
    tal.add_argument("team")
    tal.add_argument("name")
    tal.add_argument("--from", dest="from_season", default="")
    tal.add_argument("--to", default="")
    trn = tsub.add_parser("rename")
    trn.add_argument("team")
    trn.add_argument("name")
    trn.add_argument("--season", required=True)
    tm = tsub.add_parser("merge", help="fold <team> into <name>")
    tm.add_argument("team")
    tm.add_argument("name")
    tm.add_argument("--season", required=True)
    tk = tsub.add_parser("link", help="record a merged/combined team and the teams it came from or split into")
    tk.add_argument("team", help="the combined team")
    tk.add_argument("--parts", nargs="+", required=True)
    tk.add_argument("--season", required=True, help="season the combined team played")
    tk.add_argument("--note")
    for act in ("hiatus", "dissolve", "activate"):
        x = tsub.add_parser(act)
        x.add_argument("team")
        x.add_argument("--season", required=True)
        x.add_argument("--note")
    t.set_defaults(fn=cmd_teams)

    bt = sub.add_parser("backtest", help="score predictions / tune parameters")
    bt.add_argument("--seasons", nargs="*")
    bt.add_argument("--method", nargs="*", default=["legacy-v0", "v1"])
    bt.add_argument("--grid", action="store_true")
    bt.add_argument("--k", default="30,45,60,75,90")
    bt.add_argument("--scale", default="400,500,600,800")
    bt.add_argument("--chained", action="store_true", help="test between-season regression values")
    bt.add_argument("--regression", default="0,0.25,0.33,0.5,0.75,1")
    bt.set_defaults(fn=cmd_backtest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except (KeyError, ValueError, FileExistsError, FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
