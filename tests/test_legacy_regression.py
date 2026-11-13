"""The legacy-v0 method must reproduce the old scripts' published outputs exactly."""

import pandas as pd
import pytest

from khl_elo.config import load_method_config, load_seasons
from khl_elo.engine import replay
from khl_elo.ingest import load_schedule
from khl_elo.methods.legacy_v0 import LegacyV0

COMPARE = ["Team", "ELO", "Opponent", "Opp ELO", "Delta", "Win %", "Tie %", "Loss %",
           "GF", "GA", "Result", "+/- ELO", "ELO Post Game"]


def _replay_legacy(season):
    seed = pd.read_csv(season.legacy_seed)
    start = dict(zip(seed["Team"], seed["ELO"].astype(float)))
    played = load_schedule(season.schedule, raw_names=True).played
    played = played.assign(away_id=played["away_name"], home_id=played["home_name"])
    played = played.loc[played["away_id"].isin(start) & played["home_id"].isin(start)]
    return replay(played, start, LegacyV0(load_method_config("legacy-v0")))


@pytest.mark.parametrize("season_id", ["2025-fall", "2026-summer", "2026-fall"])
def test_reproduces_legacy_game_graph(season_id):
    season = next(s for s in load_seasons() if s.id == season_id)
    rr = _replay_legacy(season)
    old = pd.read_csv(season.legacy_team_games)
    new = rr.team_games[COMPARE].reset_index(drop=True)
    assert len(new) == len(old)
    pd.testing.assert_frame_equal(new, old[COMPARE].reset_index(drop=True), check_dtype=False)

    ratings = pd.read_csv(season.legacy_ratings)
    final = {t: int(v) for t, v in rr.final.items()}  # legacy truncated
    for r in ratings.itertuples():
        assert final[r.Team] == r.ELO, r.Team
