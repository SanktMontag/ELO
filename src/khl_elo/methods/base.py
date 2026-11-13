"""Shared method interface and the standard ELO building blocks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass
class GameUpdate:
    away_expected: float          # E for away (0..1)
    away_probs: tuple[float, float, float]  # away win, tie, loss
    home_probs: tuple[float, float, float]
    away_delta: float
    home_delta: float


class Method:
    """Base class. Subclasses override `update` and optionally the helpers."""

    name = "base"
    # Round (True) or truncate (False) ratings when writing the ratings table.
    round_final = True

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.scale = float(cfg.get("scale", 400))
        self.k = float(cfg.get("k", 32))
        self.draw_factor = float(cfg.get("draw_factor", 0.888))

    @property
    def description(self) -> str:
        return self.cfg.get("description", self.name)

    def params_hash(self) -> str:
        blob = json.dumps(self.cfg, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:12]

    # --- standard pieces ---
    def expected(self, ra: float, rb: float) -> float:
        """Expected score for A vs B on the logistic curve (base 10, `scale`)."""
        return 1.0 / (1.0 + 10 ** ((rb - ra) / self.scale))

    def outcome_probs(self, e: float) -> tuple[float, float, float]:
        """Split an expected score into (win, tie, loss) so that win + tie/2 == e."""
        d = self.draw_factor
        win = d * e * (1 - e) + e * e
        tie = 2 * (e - win)
        return win, tie, 1 - win - tie

    @staticmethod
    def result(gf: int, ga: int) -> float:
        return 1.0 if gf > ga else 0.0 if gf < ga else 0.5

    def gd_multiplier(self, gd: int) -> float:
        return 1.0

    # --- hooks ---
    def update(self, ra: float, rb: float, ga: int, gb: int, ctx: dict | None = None) -> GameUpdate:
        raise NotImplementedError

    def predict(self, ra: float, rb: float) -> GameUpdate:
        e = self.expected(ra, rb)
        return GameUpdate(e, self.outcome_probs(e), self.outcome_probs(1 - e), 0.0, 0.0)
