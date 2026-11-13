# KHL ELO

ELO ratings for the Kraken Hockey League ladder: Division 1 through Division 10, including lettered tiers
such as 6B. 40+ and Women's divisions are skipped automatically.

**Contents**
1. [One-time setup](#1-one-time-setup)
2. [Every session: activate the environment](#2-every-session-activate-the-environment)
3. [Weekly update](#3-weekly-update)
4. [Handling team changes](#4-handling-team-changes)
5. [End of a season](#5-end-of-a-season)
6. [Starting a new season](#6-starting-a-new-season)
7. [Once a season: check and tune the model](#7-once-a-season-check-and-tune-the-model)
8. [Testing method changes (v2-dev)](#8-testing-method-changes-v2-dev)
9. [Fixing mistakes](#9-fixing-mistakes)
10. [Reading the review messages](#10-reading-the-review-messages)
11. [How the ratings work](#11-how-the-ratings-work)
12. [Command reference](#12-command-reference)
13. [Project layout](#13-project-layout)

---

## 1. One-time setup

Only needed on a new computer, or if `.venv` gets deleted.

```powershell
cd C:\Users\Daniel\Desktop\ELO-main_2\khl-elo
py -3.14 -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m pytest          # all tests should pass
```

**Publishing:** the website runs `app/streamlit_app.py` on Streamlit Community Cloud, from this project's
GitHub repo. `requirements.txt` installs the project. The site only reads files in `output/`, so changes
appear once you commit and push.

## 2. Every session: activate the environment

```powershell
cd C:\Users\Daniel\Desktop\ELO-main_2\khl-elo
.venv\Scripts\Activate.ps1
```

`khl` is now available. `khl -h` lists the commands, and `khl <command> -h` shows the options for one
command (for example `khl import -h`).

The examples below use `2026-fall`. Replace it with the current season's id from `config/seasons.toml`.

## 3. Weekly update

### Step 1: export from the league site
1. Go to <https://krakenhockeyleague.com/schedule>.
2. Choose a date range that covers the games played since your last update. Including the coming week as
   well gives the site its upcoming-game predictions. Overlapping a previous export is fine.
3. Leave the division filter on **all** divisions.
4. Click **Export CSV**. The file usually lands in Downloads as `schedule_export(N).csv`.

### Step 2: preview the import
```powershell
khl import 2026-fall "$HOME\Downloads\schedule_export(15).csv" --dry-run
```
This writes nothing. It lists:
- **New games:** games not yet in the season.
- **Scores added:** results now posted.
- **Scores corrected:** a posted score that changed.
- **Rescheduled:** the same Kraken game moved to a new date.
- **Removed:** unplayed games inside the export's dates that are no longer listed, meaning they were
  cancelled or moved.
- **Warnings:** read these. For example, the export left out a played game; the result is always kept.

### Step 3: import and recompute
```powershell
khl import 2026-fall "$HOME\Downloads\schedule_export(15).csv" --run
```
This does four things:
1. Merges the export into the season's game list, `data/raw/schedules/2026-fall.csv`.
2. Archives the export, plus a copy of the game list as it was before, in `data/raw/imports/2026-fall/`.
3. Checks team names and divisions (see [section 10](#10-reading-the-review-messages)).
4. Recomputes the ratings into `output/2026-fall/v1/`, but only if every team name is known.

If you exported only **some** divisions, add `--no-prune`. Otherwise games in the other divisions inside
those dates would look cancelled.

### Step 4: resolve unknown team names (only if step 3 reports any)
```powershell
khl teams resolve 2026-fall
```
For each unknown name, choose one option:

| Key | Meaning |
|---|---|
| `1`, `2`, `3` | It's this existing team. Answer **Y** to make it the team's current name (a rename), or **n** to keep it as an alternate spelling. |
| `n` | It's a brand new team. It gets its division's average rating. |
| `t` | Type an existing team's name or id yourself. |
| `s` | Skip it for now. |
| `q` | Quit. Answers so far are saved. |

Then recompute:
```powershell
khl run 2026-fall
```

### Step 5: check the site
```powershell
streamlit run app\streamlit_app.py
```
Check that the "Through" date under the title matches the last game played, and that the top of the
rankings looks sensible.

### Step 6: publish
```powershell
git add -A
git commit -m "Update ratings through <date>"
git push
```

## 4. Handling team changes

A team can be referred to by its id (`T0042`), its current name, or any former name.
Run `khl teams history "<team>"` to see a team's names, status, merger links and change log.

| What happened | What to do |
|---|---|
| A team changed its name | Usually handled in `khl teams resolve` (pick the team, answer **Y**). Manually: `khl teams rename "Old Name" "New Name" --season 2026-fall` |
| The schedule spells a team two ways | `khl teams alias "Team" "Other Spelling"` |
| A brand new team | Pick **n** in `resolve`, or run `khl teams add "Name" --season 2026-fall` |
| Two teams merged for a season | 1. Let `resolve` add the merged name (for example `TP6/Fossils`) as a **new** team. 2. `khl teams link "TP6/Fossils" --parts "Trash Pandas" "Fossils" --season 2026-summer --note "summer merger"` |
| A merged team split back up | `khl teams dissolve "TP6/Fossils" --season 2026-fall`. Each part automatically starts its next season from the merged team's rating. |
| A team is taking a season off | Nothing; `khl season close` handles it ([section 5](#5-end-of-a-season)). Manually: `khl teams hiatus "Team" --season 2026-fall` |
| A team folded for good | `khl teams dissolve "Team" --season 2026-fall` |
| A team you thought folded is back | Nothing; playing again makes it active. Manually: `khl teams activate "Team" --season 2027-winter` |
| The same team ended up with two ids | `khl teams merge <duplicate id> <id to keep> --season 2026-fall`, then `khl run 2026-fall` |
| Overview | `khl teams list` or `khl teams list --status hiatus` |

The registry files in `data/registry/` are plain CSV and can also be edited in Excel:

| File | Contents |
|---|---|
| `teams.csv` | id, current name, status (`active` / `hiatus` / `dissolved`), first season, notes |
| `aliases.csv` | every name each team has used; `from_season` / `to_season` limit when a name applies |
| `lineage.csv` | merged teams and the teams they came from or split into |
| `events.csv` | log of every change (renames, status changes, merges) |

After editing them by hand, run `khl ingest 2026-fall`. It refuses to load broken registry files and says
what's wrong.

## 5. End of a season

1. Import the final export and recompute, as in [section 3](#3-weekly-update). Confirm the last games
   have scores.
2. Mark teams that played no games as on hiatus:
   ```powershell
   khl season close 2026-fall
   ```
3. Commit and push.

## 6. Starting a new season

### Step 1: add the season to `config/seasons.toml`
Copy the last block to the bottom of the file and edit it:
```toml
[[season]]
id = "2027-winter"
label = "Winter 2027"
legacy = false
schedule = "data/raw/schedules/2027-winter.csv"
seed = "data/seeds/2027-winter.csv"
methods = ["v1"]
```
Keep seasons in date order, oldest first. The order is how the system counts missed seasons.

### Step 2: import the first export
Export the new season's schedule (even if it only lists the first few weeks) and import it **without**
`--run`. There are no starting ratings yet.
```powershell
khl import 2027-winter "$HOME\Downloads\schedule_export(20).csv"
```

### Step 3: resolve names
```powershell
khl teams resolve 2027-winter
```
Pay attention here: renames, merged teams and returning teams all show up as unknown names.
See [section 4](#4-handling-team-changes).

### Step 4: build the starting ratings
```powershell
khl season new 2027-winter
```
This writes `data/seeds/2027-winter.csv`:

| Team type | Starting rating |
|---|---|
| Played last season | Final rating, pulled **50%** toward the average of the division it's in now |
| Missed 1 season | Pulled **75%** toward the division average |
| Missed 2+ seasons | The division average |
| Split from a merged team | The merged team's rating, then the rules above |
| New team | The division average (or the average of the neighbouring divisions if it's alone) |

The `source` column explains each number. **Review the file in Excel** and change any `elo` you
disagree with. Your edits are kept.

### Step 5: compute
```powershell
khl run 2027-winter
```
Then continue with the weekly update. A team that only appears in a later export is seeded automatically
with the same rules and added to the seed file. `run` reports it as `auto_seeded`.

### Step 6: close the previous season (once it's completely finished)
```powershell
khl season close 2026-fall
```

## 7. Once a season: check and tune the model

```powershell
khl backtest                          # how well the ratings predicted results, legacy vs v1
khl backtest --method v1 --chained    # re-check the between-season regression (currently 50%)
khl backtest --method v1 --grid       # re-check K and scale
python -m pytest                      # all tests should pass
```
Lower `es_brier` and `logloss` are better. In the calibration table, the `predicted` and `actual` columns
should be close.

To change a setting:
1. Edit `config/methods/v1.toml`, and note the evidence in the comments there, as the current values do.
2. Re-run the current season: `khl run 2026-fall`.
3. Commit and push.

Add each finished season to the backtest by giving its block in `seasons.toml` a `legacy_seed` file with
`Team`, `Div` and `ELO` columns.

## 8. Testing method changes (v2-dev)

`v2-dev` is a sandbox. Its settings are in `config/methods/v2-dev.toml`, and its code is in
`src/khl_elo/methods/v2_dev.py`.

```powershell
khl run 2026-fall --method v2-dev          # writes output/2026-fall/v2-dev/, never touches v1
khl backtest --method v1 v2-dev            # compare the two methods on past seasons
```
When v2 is clearly better, promote it on purpose: make it the method in `seasons.toml` (or copy its
settings into `v1.toml`), and record the change.

## 9. Fixing mistakes

| Problem | Fix |
|---|---|
| Imported the wrong file | Copy the newest `*_ledger_before.csv` from `data/raw/imports/<season>/` over `data/raw/schedules/<season>.csv`, then `khl run <season>` |
| Matched a name to the wrong team | `khl teams history "<name>"` to see where it went. Remove that row from `data/registry/aliases.csv`, then `khl teams resolve <season>` again |
| A starting rating is wrong | Edit `elo` in `data/seeds/<season>.csv`, then `khl run <season>` |
| The site shows old data | Check that `output/<season>/v1/` was committed and pushed |
| `error: ... is ambiguous` | Two teams share a name in that season. Give one of them a season range in `aliases.csv` |
| Anything else | Every run rebuilds the season from scratch (starting ratings + game list), so fixing an input and re-running always gives a consistent result |

The whole project is in git, so `git diff` shows exactly what any command changed, and
`git checkout -- <file>` undoes changes you haven't committed.

## 10. Reading the review messages

`import`, `ingest` and `run` print a review table. Results are also saved to
`output/<season>/v1/review.csv`.

| Kind | Meaning | Action |
|---|---|---|
| `unknown_name` | A team name isn't in the registry. `run` won't proceed. | `khl teams resolve <season>` |
| `inactive_team_playing` | A team marked hiatus or dissolved is in the schedule | None; it's set active on the next run. If it was dissolved on purpose, check that it's really the same team |
| `division_change` | The team's latest specific division label differs from its starting division | Informational (promotion or relegation) |
| `division_fallback` | The team only had generic (`Division 6`) or crossover (`Division 6C,6D,7A`) labels, so it kept its previous division | Usually none |
| `auto_seeded` | A team appeared that had no starting rating; it was seeded and added to the seed file | Check the value in `data/seeds/<season>.csv` |
| `schedule_warning` | Something odd in the file (duplicate rows, unreadable dates, a ladder team playing a non-ladder team) | Read it; usually harmless |

## 11. How the ratings work

**v1** is the official method from Fall 2026 on. Its settings are in `config/methods/v1.toml`.
- **Expected score:** `E = 1 / (1 + 10^((Rb − Ra) / 800))`.
- **Update:** `ΔA = K × G × (S − E)` with K = 50, and team B gets −ΔA, so the league total never changes.
  - `S` is the result: 1 for a win, ½ for a tie, 0 for a loss.
  - `G` is the goal-differential multiplier: 1× for one goal, 1.5× for two, 1.75× for three, then +0.125×
    per extra goal, capped at 3.25×.
- **Win/Tie/Loss %:** split from `E` using a draw factor of 0.75. This is for display only.
- **Divisions:** a team's division is its own label on its most recent *specific* game. That means a
  lettered label like `6C`, or an unlettered tier like `1`. Generic and crossover labels are ignored for
  this.
- **Teams:** ratings belong to permanent team ids, so renames don't reset a team.

The settings were tuned on 3,271 past games; the numbers are recorded in `v1.toml`.
The site's **What is ELO?** page explains this in plain language and reads the live settings.

**History:** seasons before Fall 2026 were calculated by the original scripts (method `legacy-v0`). They
are kept unchanged in `data/legacy/v0/` (see the README there), and the site labels them as legacy.
The `legacy-v0` code reproduces those files exactly, which the tests check.

## 12. Command reference

| Command | Purpose |
|---|---|
| `khl import <season> <file> [--dry-run] [--no-prune] [--run]` | Merge a Kraken export into a season |
| `khl ingest <season>` | Check the season's games: unknown names and division issues |
| `khl run <season> [--method v1\|v2-dev\|legacy-v0]` | Compute ratings into `output/<season>/<method>/` |
| `khl season new <season> [--force]` | Build starting ratings for a new season (`--force` overwrites an existing seed file) |
| `khl season close <season>` | Mark teams with no games as hiatus |
| `khl teams resolve <season>` | Match unknown schedule names, one at a time |
| `khl teams list [--status S]` | List teams |
| `khl teams history <team>` | A team's names, status, merger links and log |
| `khl teams add <name> --season S` | New team |
| `khl teams rename <team> <new name> --season S` | Rename; the old name is kept as an alias |
| `khl teams alias <team> <name> [--from S] [--to S]` | Extra spelling |
| `khl teams link <combined> --parts <a> <b> --season S [--note]` | Record a merged team |
| `khl teams merge <from> <into> --season S` | Fold a duplicate id into another |
| `khl teams hiatus\|dissolve\|activate <team> --season S [--note]` | Change status |
| `khl backtest [--method ...] [--grid] [--chained]` | Score and tune the model |
| `khl bootstrap --force` | **Rebuilds the registry from scratch.** Only for the original Fall 2026 setup; never needed again |

## 13. Project layout

```
config/
  seasons.toml            list of seasons, oldest first
  methods/*.toml          settings for v1, v2-dev, legacy-v0
data/
  raw/schedules/          one game list ("ledger") per season, built by `khl import`
  raw/imports/<season>/   every imported export + the ledger before each import
  registry/               teams, aliases, lineage, events
  seeds/                  starting ratings per season (safe to hand-edit)
  legacy/v0/              frozen pre-Fall-2026 outputs, original scripts and inputs
output/<season>/<method>/ generated: ratings, team_games, games, divisions, predictions,
                          review (.csv) + run_meta.json. Never hand-edit
src/khl_elo/              pipeline code (commands are in cli.py)
app/                      Streamlit site (streamlit_app.py + pages/)
tests/                    pytest suite
```
