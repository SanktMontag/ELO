"""v1: the original model with its bugs fixed and its parameters tunable.

    E  = 1 / (1 + 10^((Rb - Ra) / scale))
    G  = goal-difference multiplier (1, 1.5, then +0.125 per extra goal, capped)
    dA = K * G * (S - E);  dB = -dA          (zero-sum, symmetric in away/home)

Win/Tie/Loss % are derived from E with `draw_factor` for display and prediction
only; they do not affect ratings.
"""

from __future__ import annotations

from .base import GameUpdate, Method


class V1(Method):
    name = "v1"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        gd = cfg.get("gd", {})
        self.gd_one = float(gd.get("one_goal", 1.0))
        self.gd_two = float(gd.get("two_goals", 1.5))
        self.gd_three = float(gd.get("three_goals", 1.75))
        self.gd_step = float(gd.get("step", 0.125))
        self.gd_cap = float(gd.get("cap", 3.25))

    def gd_multiplier(self, gd: int) -> float:
        gd = abs(int(gd))
        if gd <= 1:
            return self.gd_one
        if gd == 2:
            return self.gd_two
        return min(self.gd_cap, self.gd_three + self.gd_step * (gd - 3))

    def update(self, ra, rb, ga, gb, ctx=None) -> GameUpdate:
        e = self.expected(ra, rb)
        delta = self.k * self.gd_multiplier(ga - gb) * (self.result(ga, gb) - e)
        return GameUpdate(e, self.outcome_probs(e), self.outcome_probs(1 - e), delta, -delta)
