import pandas as pd

from khl_elo.config import get_season
from khl_elo.divisions import current_divisions, division_sort_key, is_ladder, parse_label, resolve_divisions
from khl_elo.ingest import clean_name, load_schedule


def test_parse_real_labels():
    assert parse_label("Division 6C").code == "6C"
    assert parse_label("Division 6C").letter == "C"
    assert parse_label("Division 1").letter is None
    assert parse_label("Division 6C,6D,7A").combined
    assert parse_label("Division 10A-B").combined
    assert parse_label("Division 10A-B").tier == 10
    assert parse_label("40+ Fall 26") is None
    assert parse_label("Women's Division Fall 26") is None
    assert not is_ladder("40+ Advanced Fall 26")


def test_every_label_in_fall_export_classified():
    raw = pd.read_csv(get_season("2026-fall").schedule, dtype=str)
    for lab in pd.concat([raw["Away Division"], raw["Home Division"]]).dropna().unique():
        lab = clean_name(lab)
        p = parse_label(lab)
        if lab.startswith("Division"):
            assert p is not None, lab
        else:
            assert p is None, lab


def test_sort_key_ladder_order():
    codes = ["10", "3B", "1", "3A", "2", "6D", "10A"]
    assert sorted(codes, key=division_sort_key) == ["1", "2", "3A", "3B", "6D", "10", "10A"]


def test_current_division_is_latest_label_verbatim():
    rows = pd.DataFrame({
        "team_id": ["A", "A", "B", "B", "C", "D", "D"],
        "division_label": ["Division 9", "Division 10A-B", "Division 7", "Division 6D/7A", "Division 1",
                           "Division 9", "40+ Fall 26"],
        "order": [2, 1, 1, 2, 1, 1, 2],
    })
    cur, flags = current_divisions(rows, fallback={"B": "7A", "E": "5C"})
    assert cur["A"] == "9"                          # order wins, not row position
    assert cur["B"] == "6D/7A" and "B" not in flags  # odd grouping kept as-is, no fallback
    assert cur["C"] == "1"
    assert cur["D"] == "9"                          # non-ladder labels skipped
    assert not flags

    rows = pd.DataFrame({"team_id": ["E"], "division_label": ["40+ Fall 26"], "order": [1]})
    cur, flags = current_divisions(rows, fallback={"E": "5C"})
    assert cur["E"] == "5C" and "E" in flags        # no ladder label at all -> fallback


def test_bare_tier_in_lettered_tier_needs_confirmation():
    rows = pd.DataFrame({
        "team_id": ["S", "S", "X", "Y"],
        "division_label": ["Division 3", "Division 3", "Division 3B", "Division 2"],
        "order": [1, 2, 1, 1],
    })
    seed = {"S": "3B", "Z": "3A"}             # 3A only known from the seed file
    picks = resolve_divisions(rows, fallback=seed)
    assert picks["S"].source == "unconfirmed"
    assert picks["S"].candidates == ["3A", "3B"]
    assert picks["S"].division == "3B"         # provisional: previous division
    assert picks["Y"].source == "label"        # tier 2 isn't lettered -> bare "2" is fine
    cur, flags = current_divisions(rows, fallback=seed)
    assert flags["S"][0] == "division_unconfirmed" and "Y" not in flags

    # confirmed answer is used while the latest label is unchanged ...
    cur, flags = current_divisions(rows, fallback=seed, confirmed={"S": ("3", "3A")})
    assert cur["S"] == "3A" and not flags
    # ... and a new, different label from a later import wins over it
    later = pd.concat([rows, pd.DataFrame({"team_id": ["S"], "division_label": ["Division 3B"], "order": [3]})])
    cur, flags = current_divisions(later, fallback=seed, confirmed={"S": ("3", "3A")})
    assert cur["S"] == "3B" and not flags


def test_override_of_specific_label_holds_until_label_changes():
    rows = pd.DataFrame({"team_id": ["A"], "division_label": ["Division 10A-B"], "order": [1]})
    cur, _ = current_divisions(rows, confirmed={"A": ("10A-B", "10A")})
    assert cur["A"] == "10A"


def test_fall_2026_ice_breakers_in_10ab():
    from khl_elo.engine import prepare
    from khl_elo.ingest import team_rows
    from khl_elo.registry import Registry

    reg = Registry.load()
    sched, ids, _, res = prepare(get_season("2026-fall"), reg)
    g = pd.concat([sched.played, sched.upcoming], ignore_index=True)
    g = g.assign(away_id=g["away_name"].map(ids), home_id=g["home_name"].map(ids))
    cur, _ = current_divisions(team_rows(g))
    by_name = {reg.name_of(t): d for t, d in cur.items()}
    assert by_name["Ice Breakers"] == "10A-B"
    assert by_name["Seattle Seals"] == "6D/7A"


def test_clean_name():
    assert clean_name("Women''s  Red ") == "Women's Red"
    assert clean_name("Flying Monkeys ") == "Flying Monkeys"


def test_ingest_fall_2026_counts():
    s = load_schedule(get_season("2026-fall").schedule)
    assert len(s.played) == 374          # same as legacy game graph (748 team rows)
    assert s.played["date"].is_monotonic_increasing
    assert not s.played["game_id"].duplicated().any()
