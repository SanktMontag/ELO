"""`khl import`: merging partial Kraken exports into a season ledger."""

import pandas as pd
import pytest

from khl_elo import importer
from khl_elo.config import Season
from khl_elo.ingest import load_schedule

HEADER = ["Game#", "Date", "Time", "Duration", "End Time", "Arena", "Away Team", "Away Score", "Home Team",
          "Home Score", "Away Division", "Home Division", "Scoresheet", "Preview", "Game Type", "Summary", "Recap"]


def export(path, rows):
    """rows: (kraken_id, date 'Nov 14, 2026', away, away_score, home, home_score)"""
    recs = []
    for kid, d, a, sa, h, sh in rows:
        recs.append({"Game#": "", "Date": d, "Time": "9:00 PM", "Duration": "", "End Time": "", "Arena": "KCI",
                     "Away Team": a, "Away Score": sa, "Home Team": h, "Home Score": sh,
                     "Away Division": "Division 9B", "Home Division": "Division 9B",
                     "Scoresheet": f"https://krakenhockeyleague.com/scoresheet/{kid}" if kid else "",
                     "Preview": "", "Game Type": "", "Summary": "", "Recap": ""})
    pd.DataFrame(recs, columns=HEADER).to_csv(path, index=False, encoding="utf-8-sig")
    return path


@pytest.fixture
def season(tmp_path, monkeypatch):
    s = Season(id="t", label="T", legacy=False, schedule=tmp_path / "ledger.csv", seed=None, methods=("v1",))
    monkeypatch.setattr(importer, "get_season", lambda _id: s)
    monkeypatch.setattr(importer, "DATA_DIR", tmp_path)
    return s


def test_add_then_scores_then_idempotent(season, tmp_path):
    e1 = export(tmp_path / "e1.csv", [("1", "Nov 14, 2026", "A", "", "B", ""),
                                      ("2", "Nov 15, 2026", "C", "", "D", "")])
    r = importer.import_export("t", e1)
    assert len(r.added) == 2
    e2 = export(tmp_path / "e2.csv", [("1", "Nov 14, 2026", "A", "3", "B", "2")])
    r = importer.import_export("t", e2)
    assert len(r.scored) == 1 and not r.added and not r.pruned   # game 2 outside window: kept
    r = importer.import_export("t", e2)
    assert not r.changed and r.unchanged == 1
    sched = load_schedule(season.schedule)
    assert len(sched.played) == 1 and len(sched.upcoming) == 1
    assert sched.played["game_id"].iat[0] == "K1"


def test_correction_reschedule_and_prune(season, tmp_path):
    importer.import_export("t", export(tmp_path / "a.csv", [
        ("1", "Nov 14, 2026", "A", "3", "B", "2"),
        ("2", "Nov 14, 2026", "C", "", "D", ""),
        ("3", "Nov 15, 2026", "E", "", "F", ""),
    ]))
    r = importer.import_export("t", export(tmp_path / "b.csv", [
        ("1", "Nov 14, 2026", "A", "3", "B", "3"),     # score corrected
        ("2", "Nov 20, 2026", "C", "", "D", ""),       # rescheduled (same Kraken id)
    ]))                                                # game 3 (unplayed, in window) cancelled
    assert len(r.corrected) == 1
    assert len(r.rescheduled) == 1
    assert len(r.pruned) == 1 and "E @ F" in r.pruned[0]
    led = pd.read_csv(season.schedule, dtype=str, keep_default_na=False)
    assert set(led["Kraken ID"]) == {"1", "2"}
    assert led.loc[led["Kraken ID"] == "2", "Date"].iat[0] == "2026-11-20"


def test_played_game_never_lost(season, tmp_path):
    importer.import_export("t", export(tmp_path / "a.csv", [("1", "Nov 14, 2026", "A", "3", "B", "2"),
                                                            ("9", "Nov 15, 2026", "X", "", "Y", "")]))
    r = importer.import_export("t", export(tmp_path / "b.csv", [("1", "Nov 14, 2026", "A", "", "B", ""),
                                                                ("9", "Nov 15, 2026", "X", "", "Y", "")]))
    assert any("kept existing score" in w for w in r.warnings)
    assert len(load_schedule(season.schedule).played) == 1


def test_old_format_matches_by_date_and_teams(season, tmp_path):
    old = tmp_path / "old.csv"
    pd.DataFrame([{"Game#": "", "Date": "14-Nov-26", "Arena": "", "Away Team": "Flying Monkeys ",
                   "Away Score": "", "Home Team": "B", "Home Score": "", "Away Division": "Division 6",
                   "Home Division": "Division 6", "Game Type": "REG"}]).to_csv(old, index=False)
    importer.import_export("t", old)
    r = importer.import_export("t", export(tmp_path / "n.csv", [("77", "Nov 14, 2026", "Flying Monkeys", "1", "B", "0")]))
    assert len(r.scored) == 1 and not r.added           # matched despite trailing space / no id
