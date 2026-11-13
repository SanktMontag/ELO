"""Bit-for-bit port of the original scripts, for regression tests and comparison only."""

from __future__ import annotations

from .base import GameUpdate, Method

LEGACY_GD = {1: 1, 2: 1.5, 3: 1.75, 4: 1.875, 5: 2, 6: 2.125, 7: 2.25, 8: 2.375, 9: 2.5,
             10: 2.625, 11: 2.75, 12: 2.875, 13: 3, 14: 3.125, 15: 3.25}


class LegacyV0(Method):
    name = "legacy-v0"
    round_final = False  # old script used astype(int64) -> truncation

    def expected(self, ra: float, rb: float) -> float:
        qa, qb = 10 ** (ra / self.scale), 10 ** (rb / self.scale)
        return qa / (qa + qb)

    def gd_multiplier(self, gd: int) -> float:
        return LEGACY_GD.get(abs(gd), 1)

    def update(self, ra, rb, ga, gb, ctx=None) -> GameUpdate:
        e = self.expected(ra, rb)
        away_probs = self.outcome_probs(e)
        home_probs = self.outcome_probs(1 - e)
        # Known bug kept on purpose: uses P(win) instead of the expected score.
        delta = self.k * self.gd_multiplier(ga - gb) * (self.result(ga, gb) - away_probs[0])
        return GameUpdate(e, away_probs, home_probs, delta, -delta)
