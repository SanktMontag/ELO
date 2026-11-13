"""v2-dev: development track for the Design_Description.txt model.

Currently behaves exactly like v1 plus a provisional K-factor for teams with few
games. Planned additions (see legacy Design_Description.txt):
  * contextual goal-difference multiplier (z-score vs. ELO-delta bins)
  * Gaussian draw-probability model
  * form-weighted predictions (prediction only, not rating updates)

Outputs go to output/<season>/v2-dev/ and never overwrite v1.
"""

from __future__ import annotations

from .base import GameUpdate
from .v1 import V1


class V2Dev(V1):
    name = "v2-dev"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        prov = cfg.get("provisional", {})
        self.prov_games = int(prov.get("games", 0))
        self.prov_boost = float(prov.get("boost", 1.0))

    def k_for(self, games_played: int) -> float:
        if self.prov_games <= 0 or games_played >= self.prov_games:
            return self.k
        progress = games_played / self.prov_games
        return self.k * (self.prov_boost - (self.prov_boost - 1.0) * progress)

    def update(self, ra, rb, ga, gb, ctx=None) -> GameUpdate:
        ctx = ctx or {}
        e = self.expected(ra, rb)
        g = self.gd_multiplier(ga - gb)
        s = self.result(ga, gb)
        # Same G for both sides; K may differ, so not exactly zero-sum while provisional.
        ka = self.k_for(ctx.get("away_gp", 0)) if ctx.get("away_new") else self.k
        kh = self.k_for(ctx.get("home_gp", 0)) if ctx.get("home_new") else self.k
        da = ka * g * (s - e)
        db = kh * g * ((1 - s) - (1 - e))
        return GameUpdate(e, self.outcome_probs(e), self.outcome_probs(1 - e), da, db)
