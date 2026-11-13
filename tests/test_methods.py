import pytest

from khl_elo.config import load_method_config
from khl_elo.methods import get_method
from khl_elo.methods.v1 import V1


@pytest.fixture
def v1():
    return get_method("v1")


def test_even_tie_is_zero(v1):
    u = v1.update(1500, 1500, 2, 2)
    assert u.away_delta == pytest.approx(0)
    assert u.home_delta == pytest.approx(0)


def test_zero_sum_and_symmetric(v1):
    a = v1.update(1600, 1400, 1, 3)
    assert a.away_delta + a.home_delta == pytest.approx(0)
    # swapping away/home gives the mirror image
    b = v1.update(1400, 1600, 3, 1)
    assert b.home_delta == pytest.approx(a.away_delta)


def test_probs_consistent_with_expected(v1):
    for e in (0.1, 0.5, 0.73, 0.99):
        w, t, l = v1.outcome_probs(e)
        assert w + t + l == pytest.approx(1)
        assert w + t / 2 == pytest.approx(e)
        assert min(w, t, l) >= 0


def test_gd_monotone_and_capped(v1):
    vals = [v1.gd_multiplier(g) for g in range(0, 40)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))
    assert vals[0] == vals[1] == 1.0
    assert vals[2] == 1.5
    assert vals[3] == 1.75
    assert max(vals) == v1.gd_cap
    assert v1.gd_multiplier(16) == v1.gd_cap  # legacy fell back to 1x here


def test_favourite_win_gains_less_than_underdog_win(v1):
    fav = v1.update(1700, 1500, 3, 2).away_delta
    dog = v1.update(1500, 1700, 3, 2).away_delta
    assert 0 < fav < dog


def test_v2_dev_provisional_only_for_new_teams():
    m = get_method("v2-dev")
    base = m.update(1500, 1500, 3, 2, {"away_gp": 0, "home_gp": 0})
    new = m.update(1500, 1500, 3, 2, {"away_gp": 0, "home_gp": 0, "away_new": True})
    assert new.away_delta == pytest.approx(base.away_delta * m.prov_boost)
    assert new.home_delta == pytest.approx(base.home_delta)


def test_config_overrides():
    m = V1({**load_method_config("v1"), "k": 10})
    assert m.k == 10
