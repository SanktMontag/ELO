"""Calculate and export Fall 2026 hockey Elo ratings."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from dateutil.parser import parse


SCHEDULE_FILE = "fall_schedule_26.csv"
INITIAL_RATINGS_FILE = "initial_26_Fall.csv"
GAMELOG_FILE = "output_gamelog_fall_26.csv"
RATINGS_FILE = "output_ratings_fall_26.csv"
GAME_GRAPH_FILE = "game_graph_fall_26.csv"

K_FACTOR = 75
DRAW_FACTOR = 0.888

EXCLUDED_TEAMS = {
    "40+ Advanced White",
    "40+ Advanced Sky Blue",
    "40+ Advanced Green",
    "40+ Advanced Orange",
    "40+ Advanced Grey",
    "40+ Advanced Black",
    "40+ Advanced Red",
    "40+ Grey",
    "40+ Red",
    "40+ White",
    "40+ Sky Blue",
    "40+ Royal",
    "40+ Yellow",
    "40+ Orange",
    "40+ Navy",
    "Black Sheesh",
    "Blue Footed Bloobies",
    "Grey Dust Bunnies",
    "Pineapple Express",
    "Red Hots",
    "White Yetis",
    "Isotopes-Cascade",
    "Razor Clams - Cascade",
    "Warriors - Cascade",
    "Grizzlies-Cascade",
    "Tigers-Cascade",
    "Cascade Lumberjacks-Cascade",
    "Lumberjacks-Cascade",
    "Wolverines-Cascade",
    "United-Cascade",
    "Kelly Days-Cascade",
    "Fighting Saints-Cascade",
    "Coppernails-Cascade",
    "Women''s Yellow",
    "Women''s Green",
    "Women''s White",
    "Women''s Orange",
    "Women''s Sky Blue",
    "Women''s Pink",
    "Women''s Red",
    "Women''s Purple",
    "Women''s #7",
    "Women''s #8",
    "Women''s Royal",
    "Women''s Black",
    "40+ Advanced Baines",
    "40+ Advanced Puck Hogs",
    "40+ Advanced 40 Proof",
    "40+ Advanced Bakers Dozen",
    "40+ Advanced Falk",
    "40+ Advanced Gritty Pylons",
    "40+ Assisted Living",
    "40+ Puck Dynasty",
    "40+ Swift",
    "40+ Mid-Ice Crisis",
    "40+ Rough Draft",
    "40+ Red Flags",
    "40+ Keller",
    "40+ Carls Seniors",
    "40+ Coldtimers",
    "40+ Elder Skatesmen",
    "40+ Geri Hat Tricks",
    "40+ Carl''s Seniors",
    "40+ Gritty Pylons",
    "40+ Old Navy",
    "Rink Flamingos",
    "Black Sheep-Cascade",
    "40+ Advanced Gratiot",
    "40+ Advanced Tagami",
    "40+ Rusty Blades",
    "40+ Old Navy (5)",
    "40+ Geri Hat Tricks (4)",
    "40+ Carl''s Seniors (6)",
    "40+ Coldtimers (3)",
    "40+ Red Flags (2)",
    "40+ Advanced Whalers",
    "40+ Advanced Spoilers",
    "Otters",
    "Shake N Bake",
}

GOAL_DIFFERENCE_MULTIPLIERS = {
    1: 1,
    2: 1.5,
    3: 1.75,
    4: 1.875,
    5: 2,
    6: 2.125,
    7: 2.25,
    8: 2.375,
    9: 2.5,
    10: 2.625,
    11: 2.75,
    12: 2.875,
    13: 3,
    14: 3.125,
    15: 3.25,
}

GAME_GRAPH_COLUMNS = [
    "Date",
    "Team",
    "ELO",
    "Opponent",
    "Opp ELO",
    "Delta",
    "Win %",
    "Tie %",
    "Loss %",
    "GF",
    "GA",
    "Result",
    "+/- ELO",
    "ELO Post Game",
]


def load_games(schedule_path: Path) -> pd.DataFrame:
    """Load scored games, remove excluded teams, and prepare output columns."""
    games = pd.read_csv(schedule_path)
    games = games.loc[games["Away Score"].notna()].copy()
    retained = ~games["Away Team"].isin(EXCLUDED_TEAMS) & ~games[
        "Home Team"
    ].isin(EXCLUDED_TEAMS)
    games = games.loc[retained].reset_index(drop=True)

    games["Date"] = games["Date"].map(
        lambda value: datetime.strftime(parse(str(value)), "%m/%d/%y")
    )
    games.drop(columns=["Game#"], inplace=True)
    games["Away Score"] = games["Away Score"].astype("Int64")
    games["Home Score"] = games["Home Score"].astype("Int64")
    games["Game_ID"] = games.apply(
        lambda game: (
            f"{game['Date']}_{game['Away Team']}_@_{game['Home Team']}"
        ),
        axis=1,
    )

    for side in ("Away", "Home"):
        games[f"{side} ELO Prior"] = 0.0
        games[f"{side} EA"] = 0.0
        games[f"{side} ELO Posterior"] = 0.0
        games[f"{side} Delta"] = 0

    return games


def expected_scores(away_elo: float, home_elo: float) -> tuple[float, float]:
    """Return the two teams' expected scores on a 0-to-1 scale."""
    away_q = 10 ** (away_elo / 400)
    home_q = 10 ** (home_elo / 400)
    denominator = away_q + home_q
    return away_q / denominator, home_q / denominator


def expected_outcomes(expected_score: float) -> tuple[float, float, float]:
    """Return win, tie, and loss probabilities for an expected score."""
    win = DRAW_FACTOR * (expected_score * (1 - expected_score)) + expected_score**2
    tie = 2 * (expected_score - win)
    loss = 1 - win - tie
    return win, tie, loss


def result_score(own_score: int, opponent_score: int) -> float:
    if own_score > opponent_score:
        return 1.0
    if own_score < opponent_score:
        return 0.0
    return 0.5


def process_games(
    games: pd.DataFrame, initial_ratings: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Apply each game's Elo change and build the ratings and game graph."""
    games = games.copy()
    ratings = initial_ratings.copy().reset_index(drop=True)
    ratings["ELO"] = ratings["ELO"].astype("float64")

    team_indexes: dict[str, int] = {}
    for index, team in enumerate(ratings["Team"]):
        team_indexes.setdefault(team, index)

    graph_records: list[dict[str, object]] = []
    for index, game in games.iterrows():
        away_team = game["Away Team"]
        home_team = game["Home Team"]
        if away_team not in team_indexes or home_team not in team_indexes:
            missing_team = away_team if away_team not in team_indexes else home_team
            raise ValueError(f"Team {missing_team!r} is missing from initial ratings")

        away_index = team_indexes[away_team]
        home_index = team_indexes[home_team]
        away_prior = float(ratings.at[away_index, "ELO"])
        home_prior = float(ratings.at[home_index, "ELO"])
        away_score = int(game["Away Score"])
        home_score = int(game["Home Score"])

        away_expected, home_expected = expected_scores(away_prior, home_prior)
        away_outcomes = expected_outcomes(away_expected)
        home_outcomes = expected_outcomes(home_expected)
        away_win, away_tie, away_loss = away_outcomes
        home_win, home_tie, home_loss = home_outcomes
        away_result = result_score(away_score, home_score)
        home_result = result_score(home_score, away_score)

        goal_difference = abs(away_score - home_score)
        multiplier = GOAL_DIFFERENCE_MULTIPLIERS.get(goal_difference, 1)
        away_posterior = away_prior + K_FACTOR * multiplier * (
            away_result - away_win
        )
        away_delta = away_posterior - away_prior
        home_posterior = home_prior - away_delta

        ratings.at[away_index, "ELO"] = away_posterior
        ratings.at[home_index, "ELO"] = home_posterior
        games.at[index, "Away ELO Prior"] = away_prior
        games.at[index, "Away EA"] = round(away_expected * 100, 1)
        games.at[index, "Away ELO Posterior"] = away_posterior
        games.at[index, "Home ELO Prior"] = home_prior
        games.at[index, "Home EA"] = round(home_expected * 100, 1)
        games.at[index, "Home ELO Posterior"] = home_posterior

        date = game["Date"]
        graph_records.extend(
            [
                {
                    "Date": date,
                    "Team": away_team,
                    "ELO": round(away_prior),
                    "Opponent": home_team,
                    "Opp ELO": round(home_prior),
                    "Delta": round(away_prior - home_prior),
                    "Win %": round(away_win * 100, 1),
                    "Tie %": round(away_tie * 100, 1),
                    "Loss %": round(away_loss * 100, 1),
                    "GF": away_score,
                    "GA": home_score,
                    "Result": {0.0: "Loss", 0.5: "Tie", 1.0: "Win"}[
                        away_result
                    ],
                    "+/- ELO": round(away_posterior - away_prior),
                    "ELO Post Game": round(away_posterior),
                },
                {
                    "Date": date,
                    "Team": home_team,
                    "ELO": round(home_prior),
                    "Opponent": away_team,
                    "Opp ELO": round(away_prior),
                    "Delta": round(home_prior - away_prior),
                    "Win %": round(home_win * 100, 1),
                    "Tie %": round(home_tie * 100, 1),
                    "Loss %": round(home_loss * 100, 1),
                    "GF": home_score,
                    "GA": away_score,
                    "Result": {0.0: "Loss", 0.5: "Tie", 1.0: "Win"}[
                        home_result
                    ],
                    "+/- ELO": round(home_posterior - home_prior),
                    "ELO Post Game": round(home_posterior),
                },
            ]
        )

    ratings["ELO"] = ratings["ELO"].astype("int64")
    ratings = ratings.sort_values("ELO", ascending=False).reset_index(drop=True)
    ratings["Ranking"] = ratings.index + 1
    ratings = ratings[["Ranking", "Team", "Div", "ELO"]]

    for side in ("Away", "Home"):
        games[f"{side} ELO Prior"] = games[f"{side} ELO Prior"].round().astype(
            "Int64"
        )
        games[f"{side} ELO Posterior"] = (
            games[f"{side} ELO Posterior"].round().astype("Int64")
        )
        games[f"{side} Delta"] = (
            games[f"{side} ELO Posterior"] - games[f"{side} ELO Prior"]
        )

    game_graph = pd.DataFrame(graph_records, columns=GAME_GRAPH_COLUMNS)
    return games, ratings, game_graph


def main() -> None:
    data_directory = Path(__file__).resolve().parent
    games = load_games(data_directory / SCHEDULE_FILE)
    initial_ratings = pd.read_csv(data_directory / INITIAL_RATINGS_FILE)
    game_log, ratings, game_graph = process_games(games, initial_ratings)

    for away_team, home_team in zip(
        game_log["Away Team"], game_log["Home Team"]
    ):
        print(away_team, " ", home_team)
    print(ratings.to_string(index=False))

    game_log.to_csv(data_directory / GAMELOG_FILE)
    ratings.to_csv(data_directory / RATINGS_FILE, index=False)
    game_graph.to_csv(data_directory / GAME_GRAPH_FILE, index=False)


if __name__ == "__main__":
    main()
