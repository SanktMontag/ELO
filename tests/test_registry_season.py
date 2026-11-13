import pandas as pd
import pytest

from khl_elo.config import SeasonRules
from khl_elo.registry import Registry, strip_division_suffix


def empty_registry(tmp_path):
    return Registry(pd.DataFrame(columns=["team_id", "name", "status", "first_season", "notes"]),
                    pd.DataFrame(columns=["alias", "team_id", "from_season", "to_season"]),
                    pd.DataFrame(columns=["date", "season", "team_id", "event", "detail"]), tmp_path)


def test_rename_keeps_history(tmp_path):
    reg = empty_registry(tmp_path)
    tid = reg.add_team("Monarchs 6", "2026-summer")
    reg.rename(tid, "Monarchs 6B", "2026-fall")
    assert reg.resolve("Monarchs 6") == tid
    assert reg.resolve("monarchs 6b") == tid
    assert reg.name_of(tid) == "Monarchs 6B"
    reg.save()
    again = Registry.load(tmp_path)
    assert again.resolve("Monarchs 6", "2026-summer") == tid


def test_alias_season_ranges(tmp_path):
    reg = empty_registry(tmp_path)
    a = reg.add_team("Seals", "2025-fall")
    reg.aliases.loc[reg.aliases.team_id == a, "to_season"] = "2026-summer"
    b = reg.add_team("Seattle Seals New", "2026-fall")
    reg.add_alias(b, "Seals", from_season="2026-fall")
    reg.validate()
    assert reg.resolve("Seals", "2026-summer") == a
    assert reg.resolve("Seals", "2026-fall") == b


def test_overlapping_alias_rejected(tmp_path):
    reg = empty_registry(tmp_path)
    a = reg.add_team("Alpha", "2026-fall")
    b = reg.add_team("Beta", "2026-fall")
    reg.add_alias(b, "Alpha")
    with pytest.raises(ValueError):
        reg.validate()


def test_suggestions_strip_division_suffix(tmp_path):
    reg = empty_registry(tmp_path)
    tid = reg.add_team("Spicy Kittens HC-8", "2026-summer")
    assert strip_division_suffix("Spicy Kittens HC-8A") == "Spicy Kittens"
    assert reg.suggest("Spicy Kittens HC-8A")[0][0] == tid


def test_status_and_merge(tmp_path):
    reg = empty_registry(tmp_path)
    a = reg.add_team("Old", "2026-fall")
    b = reg.add_team("New", "2026-fall")
    reg.set_status(a, "hiatus", "2026-fall")
    reg.set_status(a, "active", "2026-fall")
    assert list(reg.events["event"])[-1] == "return"
    reg.merge(a, b, "2026-fall")
    assert reg.resolve("Old") == b
    assert a not in set(reg.teams.team_id)


def test_hiatus_fraction():
    r = SeasonRules(offseason_regression=0.5, hiatus_per_season=0.25)
    assert r.hiatus_fraction(0) == 0.5
    assert r.hiatus_fraction(1) == 0.75
    assert r.hiatus_fraction(2) == 1.0
    assert r.hiatus_fraction(9) == 1.0


def test_lineage_link_and_merge(tmp_path):
    reg = empty_registry(tmp_path)
    tp = reg.add_team("Trash Pandas", "2026-fall")
    fo = reg.add_team("Fossils", "2026-fall")
    combo = reg.add_team("TP6/Fossils", "2026-summer")
    reg.link(combo, [tp, fo], "2026-summer", "summer merger")
    reg.save()
    again = Registry.load(tmp_path)
    assert set(again.related(fo)["combined_id"]) == {combo}
    assert len(again.related(combo)) == 2
    with pytest.raises(ValueError):
        again.link(combo, [combo], "2026-summer")


def test_seed_team_rules():
    from khl_elo.config import Season
    from khl_elo.seeding import nearest_division_value, seed_team

    mk = lambda i: Season(id=f"s{i}", label="", legacy=False, schedule=None, seed=None, methods=("v1",), index=i)
    now = mk(5)
    rules = SeasonRules(offseason_regression=0.5, hiatus_per_season=0.25)
    means = {"5A": 3000.0, "5C": 2800.0}
    history = {"cont": (3100.0, "5A", mk(4)), "gone1": (2600.0, "5A", mk(3))}
    assert seed_team("cont", "5A", now, history, means, rules)[0] == 3050.0            # 50% to mean
    assert seed_team("gone1", "5A", now, history, means, rules)[0] == 2600 + 0.75 * 400  # 1 missed -> 75%
    assert seed_team("new", "5A", now, history, means, rules)[:2] == (3000.0, "new team: division mean")
    assert nearest_division_value("5B", means) == 2900.0                                # empty div -> neighbours
