# Legacy outputs (method `legacy-v0`)

These files were produced by the original scripts (`raw/elo.py`, `raw/elo_summer_26.py` and
`raw/elo_fall_26.py`) and are kept unchanged as historical record.

| Season | Ratings | Game graph | Schedule | Starting ratings |
|---|---|---|---|---|
| Fall 2025 | output_ratings_fall_25.csv | game_graph_fall_25.csv | raw/fall_schedule_25.csv | raw/initial_25_Fall.csv |
| Summer 2026 | output_ratings_summer_26.csv | game_graph_summer_26.csv | raw/summer_schedule_26.csv | raw/initial_26_Summer.csv |
| Fall 2026 (superseded by v1) | output_ratings_fall_26.csv | game_graph_fall_26.csv | raw/fall_schedule_26.csv | raw/initial_26_Fall.csv |

`Combined_Game_Log.csv` is the original multi-season game log.

## How the original method differs from v1

* **Update rule:** the old scripts used `K·G·(S − P(win))` instead of `K·G·(S − E)`. Ties make `P(win) < E`,
  so the away team gained a little on average in every game: about +740 ELO in total over Fall 2026.
* **Scale and K:** scale 400 and K = 75. A backtest showed these were overconfident; v1 uses 800 and 50.
* **Draw factor:** 0.888, which predicted about 4.5% ties against roughly 11.5% actual. v1 uses 0.75.
* **Goal-difference table:** stopped at 15 goals, and anything larger fell back to 1×. v1 uses a formula
  with a cap.
* **Final ratings:** truncated instead of rounded.
* **Team names:** matched as raw strings, so `"Flying Monkeys "` (with a trailing space) and
  `"Flying Monkeys"` became two different teams.

`tests/test_legacy_regression.py` checks that the `legacy-v0` method in this repo reproduces these files
exactly, which shows that the port is faithful.
