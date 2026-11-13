"""Project paths and TOML config loading."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def project_root() -> Path:
    env = os.environ.get("KHL_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


ROOT = project_root()
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
REGISTRY_DIR = DATA_DIR / "registry"
SEEDS_DIR = DATA_DIR / "seeds"
RAW_DIR = DATA_DIR / "raw" / "schedules"
OUTPUT_DIR = ROOT / "output"


@dataclass(frozen=True)
class Season:
    id: str
    label: str
    legacy: bool
    schedule: Path | None
    seed: Path | None
    methods: tuple[str, ...]
    legacy_seed: Path | None = None
    legacy_ratings: Path | None = None
    legacy_team_games: Path | None = None
    index: int = 0

    def output_dir(self, method: str) -> Path:
        return OUTPUT_DIR / self.id / method


def _path(value: str | None) -> Path | None:
    return ROOT / value if value else None


def load_seasons() -> list[Season]:
    with open(CONFIG_DIR / "seasons.toml", "rb") as fh:
        raw = tomllib.load(fh)
    seasons = []
    for i, s in enumerate(raw.get("season", [])):
        seasons.append(
            Season(
                id=s["id"],
                label=s.get("label", s["id"]),
                legacy=bool(s.get("legacy", False)),
                schedule=_path(s.get("schedule")),
                seed=_path(s.get("seed")),
                methods=tuple(s.get("methods", ["legacy-v0"] if s.get("legacy") else ["v1"])),
                legacy_seed=_path(s.get("legacy_seed")),
                legacy_ratings=_path(s.get("legacy_ratings")),
                legacy_team_games=_path(s.get("legacy_team_games")),
                index=i,
            )
        )
    ids = [s.id for s in seasons]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate season id in seasons.toml")
    return seasons


def get_season(season_id: str) -> Season:
    for s in load_seasons():
        if s.id == season_id:
            return s
    raise KeyError(f"Unknown season {season_id!r}; add it to config/seasons.toml")


def season_order() -> dict[str, int]:
    return {s.id: s.index for s in load_seasons()}


def load_method_config(name: str) -> dict:
    path = CONFIG_DIR / "methods" / f"{name}.toml"
    if not path.exists():
        raise KeyError(f"No method config {path}")
    with open(path, "rb") as fh:
        return tomllib.load(fh)


@dataclass
class SeasonRules:
    """Season roll-over rules (from the method config's [season] table)."""

    offseason_regression: float = 0.5
    hiatus_per_season: float = 0.25
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict) -> "SeasonRules":
        s = dict(cfg.get("season", {}))
        return cls(
            offseason_regression=float(s.pop("offseason_regression", 0.5)),
            hiatus_per_season=float(s.pop("hiatus_per_season", 0.25)),
            extra=s,
        )

    def hiatus_fraction(self, missed_seasons: int) -> float:
        """Share of the gap to the division mean removed at a season boundary."""
        return min(1.0, self.offseason_regression + self.hiatus_per_season * max(0, missed_seasons))
