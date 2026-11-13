"""Team registry: stable team_ids, aliases (name history), status and events.

Files (data/registry/):
    teams.csv    team_id, name, status, first_season, notes
    aliases.csv  alias, team_id, from_season, to_season      (blank season = open-ended)
    events.csv   date, season, team_id, event, detail
    lineage.csv  combined_id, part_id, season, note
                 (a merged/combined team and the teams it was formed from or split back into)

Status values: active | hiatus | dissolved
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from .config import REGISTRY_DIR, season_order
from .ingest import clean_name, name_key

STATUSES = ("active", "hiatus", "dissolved")
TEAM_COLS = ["team_id", "name", "status", "first_season", "notes"]
ALIAS_COLS = ["alias", "team_id", "from_season", "to_season"]
EVENT_COLS = ["date", "season", "team_id", "event", "detail"]
LINEAGE_COLS = ["combined_id", "part_id", "season", "note"]

_SUFFIX_RE = re.compile(r"(\s*[-–]?\s*(HC)?[-\s]*\d{1,2}[A-Z]?)$", re.IGNORECASE)


def strip_division_suffix(name: str) -> str:
    """'Spicy Kittens HC-8A' -> 'Spicy Kittens', 'Monarchs 6B' -> 'Monarchs'."""
    out = _SUFFIX_RE.sub("", clean_name(name)).strip(" -")
    return out or clean_name(name)


@dataclass
class Registry:
    teams: pd.DataFrame
    aliases: pd.DataFrame
    events: pd.DataFrame
    directory: Path = field(default=REGISTRY_DIR)
    lineage: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=LINEAGE_COLS, dtype=str))

    # ---------- persistence ----------
    @classmethod
    def load(cls, directory: Path = REGISTRY_DIR) -> "Registry":
        def read(name, cols):
            p = directory / name
            if p.exists():
                df = pd.read_csv(p, dtype=str, keep_default_na=False)
                for c in cols:
                    if c not in df.columns:
                        df[c] = ""
                return df[cols]
            return pd.DataFrame(columns=cols, dtype=str)

        reg = cls(read("teams.csv", TEAM_COLS), read("aliases.csv", ALIAS_COLS), read("events.csv", EVENT_COLS),
                  directory, read("lineage.csv", LINEAGE_COLS))
        reg.validate()
        return reg

    def save(self) -> None:
        self.validate()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.teams.sort_values("team_id").to_csv(self.directory / "teams.csv", index=False)
        self.aliases.sort_values(["team_id", "alias"]).to_csv(self.directory / "aliases.csv", index=False)
        self.events.to_csv(self.directory / "events.csv", index=False)
        self.lineage.to_csv(self.directory / "lineage.csv", index=False)

    def validate(self) -> None:
        ids = set(self.teams["team_id"])
        bad_link = ~(self.lineage["combined_id"].isin(ids) & self.lineage["part_id"].isin(ids))
        if bad_link.any():
            raise ValueError(f"lineage.csv references unknown team_id(s): {self.lineage.loc[bad_link].values.tolist()}")
        if self.teams["team_id"].duplicated().any():
            raise ValueError(f"Duplicate team_id in teams.csv: {self.teams.loc[self.teams.team_id.duplicated(), 'team_id'].tolist()}")
        bad = ~self.teams["status"].isin(STATUSES)
        if bad.any():
            raise ValueError(f"Bad status in teams.csv: {self.teams.loc[bad, ['team_id', 'status']].values.tolist()}")
        unknown = ~self.aliases["team_id"].isin(self.teams["team_id"])
        if unknown.any():
            raise ValueError(f"aliases.csv references unknown team_id(s): {self.aliases.loc[unknown, 'team_id'].unique().tolist()}")
        # The same alias may map to different teams only in non-overlapping season ranges.
        order = season_order()
        for key, grp in self.aliases.assign(k=self.aliases["alias"].map(name_key)).groupby("k"):
            if grp["team_id"].nunique() <= 1:
                continue
            ranges = [(_rank(r.from_season, order, -1), _rank(r.to_season, order, 10**6), r.team_id) for r in grp.itertuples()]
            ranges.sort()
            for (a0, a1, ta), (b0, b1, tb) in zip(ranges, ranges[1:]):
                if ta != tb and b0 <= a1:
                    raise ValueError(f"Alias {key!r} maps to {ta} and {tb} in overlapping seasons")

    # ---------- lookups ----------
    def next_id(self) -> str:
        nums = [int(t[1:]) for t in self.teams["team_id"] if re.fullmatch(r"T\d+", t)]
        return f"T{(max(nums) + 1 if nums else 1):04d}"

    def name_of(self, team_id: str) -> str:
        row = self.teams.loc[self.teams["team_id"] == team_id]
        return row["name"].iat[0] if len(row) else team_id

    def status_of(self, team_id: str) -> str:
        row = self.teams.loc[self.teams["team_id"] == team_id]
        return row["status"].iat[0] if len(row) else ""

    def resolve(self, raw_name: str, season: str | None = None) -> str | None:
        """Map a raw schedule name to a team_id (None if unknown)."""
        key = name_key(raw_name)
        order = season_order()
        cand = self.aliases.loc[self.aliases["alias"].map(name_key) == key]
        if season is not None and len(cand):
            s = order.get(season)
            if s is not None:
                ok = cand.apply(lambda r: _rank(r.from_season, order, -1) <= s <= _rank(r.to_season, order, 10**6), axis=1)
                cand = cand.loc[ok]
        ids = cand["team_id"].unique()
        if len(ids) == 1:
            return ids[0]
        if len(ids) > 1:
            raise ValueError(f"Name {raw_name!r} is ambiguous in season {season}: {list(ids)}")
        return None

    def find(self, ref: str) -> str:
        """Accept a team_id or any alias/name; raise if not found."""
        if ref in set(self.teams["team_id"]):
            return ref
        tid = self.resolve(ref)
        if tid is None:
            sugg = self.suggest(ref)
            hint = f" Did you mean: {', '.join(f'{n} ({t})' for t, n, _ in sugg)}?" if sugg else ""
            raise KeyError(f"No team matches {ref!r}.{hint}")
        return tid

    def suggest(self, raw_name: str, n: int = 3, exclude_status: tuple[str, ...] = ("dissolved",)) -> list[tuple[str, str, float]]:
        """Fuzzy candidates as (team_id, current name, score)."""
        target = strip_division_suffix(raw_name).casefold()
        live = set(self.teams.loc[~self.teams["status"].isin(exclude_status), "team_id"])
        best: dict[str, float] = {}
        for a in self.aliases.itertuples():
            if a.team_id not in live:
                continue
            full = difflib.SequenceMatcher(None, name_key(raw_name), name_key(a.alias)).ratio()
            stem = difflib.SequenceMatcher(None, target, strip_division_suffix(a.alias).casefold()).ratio()
            score = max(full, stem)
            if score > best.get(a.team_id, 0):
                best[a.team_id] = score
        ranked = sorted(best.items(), key=lambda kv: -kv[1])[:n]
        return [(t, self.name_of(t), round(s, 2)) for t, s in ranked if s >= 0.6]

    # ---------- mutations ----------
    def log(self, season: str, team_id: str, event: str, detail: str = "") -> None:
        row = {"date": date.today().isoformat(), "season": season, "team_id": team_id, "event": event, "detail": detail}
        self.events = pd.concat([self.events, pd.DataFrame([row])], ignore_index=True)

    def add_alias(self, team_id: str, alias: str, from_season: str = "", to_season: str = "") -> None:
        alias = clean_name(alias)
        dup = (self.aliases["alias"].map(name_key) == name_key(alias)) & (self.aliases["team_id"] == team_id)
        if dup.any():
            return
        row = {"alias": alias, "team_id": team_id, "from_season": from_season, "to_season": to_season}
        self.aliases = pd.concat([self.aliases, pd.DataFrame([row])], ignore_index=True)

    def add_team(self, name: str, season: str, notes: str = "", team_id: str | None = None) -> str:
        name = clean_name(name)
        existing = self.resolve(name, season)
        if existing:
            raise ValueError(f"{name!r} already belongs to {existing}")
        tid = team_id or self.next_id()
        row = {"team_id": tid, "name": name, "status": "active", "first_season": season, "notes": notes}
        self.teams = pd.concat([self.teams, pd.DataFrame([row])], ignore_index=True)
        self.add_alias(tid, name, from_season=season)
        self.log(season, tid, "new", name)
        return tid

    def rename(self, team_id: str, new_name: str, season: str) -> None:
        new_name = clean_name(new_name)
        old = self.name_of(team_id)
        other = self.resolve(new_name, season)
        if other and other != team_id:
            raise ValueError(f"{new_name!r} already belongs to {other}; use merge instead")
        self.teams.loc[self.teams["team_id"] == team_id, "name"] = new_name
        self.add_alias(team_id, new_name, from_season=season)
        self.log(season, team_id, "rename", f"{old} -> {new_name}")

    def set_status(self, team_id: str, status: str, season: str, detail: str = "") -> None:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        old = self.status_of(team_id)
        if old == status:
            return
        self.teams.loc[self.teams["team_id"] == team_id, "status"] = status
        event = {"hiatus": "hiatus", "dissolved": "dissolve", "active": "return" if old == "hiatus" else "activate"}[status]
        self.log(season, team_id, event, detail or f"{old} -> {status}")

    def link(self, combined_id: str, part_ids: list[str], season: str, note: str = "") -> None:
        """Record that `combined_id` was formed from (and/or split back into) `part_ids`."""
        for pid in part_ids:
            if pid == combined_id:
                raise ValueError("A team cannot be part of itself")
            exists = (self.lineage["combined_id"] == combined_id) & (self.lineage["part_id"] == pid)
            if exists.any():
                continue
            row = {"combined_id": combined_id, "part_id": pid, "season": season, "note": note}
            self.lineage = pd.concat([self.lineage, pd.DataFrame([row])], ignore_index=True)
            self.log(season, pid, "lineage", f"part of {self.name_of(combined_id)} ({combined_id}). {note}".strip())
        parts = ", ".join(f"{self.name_of(p)} ({p})" for p in part_ids)
        self.log(season, combined_id, "lineage", f"combined team of {parts}. {note}".strip())

    def related(self, team_id: str) -> pd.DataFrame:
        """Lineage rows where the team is either the combined team or a part."""
        m = (self.lineage["combined_id"] == team_id) | (self.lineage["part_id"] == team_id)
        return self.lineage.loc[m]

    def merge(self, from_id: str, into_id: str, season: str) -> None:
        """Fold one team_id into another (all aliases move; from_id is removed)."""
        if from_id == into_id:
            raise ValueError("Cannot merge a team into itself")
        self.aliases.loc[self.aliases["team_id"] == from_id, "team_id"] = into_id
        for col in ("combined_id", "part_id"):
            self.lineage.loc[self.lineage[col] == from_id, col] = into_id
        name = self.name_of(from_id)
        self.teams = self.teams.loc[self.teams["team_id"] != from_id].reset_index(drop=True)
        self.log(season, into_id, "merge", f"{from_id} ({name}) merged in")


def _rank(season_id: str, order: dict[str, int], default: int) -> int:
    if not season_id:
        return default
    if season_id not in order:
        raise ValueError(f"Unknown season {season_id!r} in aliases.csv")
    return order[season_id]


@dataclass
class Resolution:
    ids: dict[str, str]                  # raw name -> team_id
    unknown: dict[str, list]             # raw name -> suggestions
    inactive: dict[str, str]             # raw name -> status (hiatus/dissolved teams appearing in schedule)


def resolve_names(reg: Registry, names: list[str], season: str) -> Resolution:
    ids, unknown, inactive = {}, {}, {}
    for n in sorted(set(names)):
        tid = reg.resolve(n, season)
        if tid is None:
            unknown[n] = reg.suggest(n, exclude_status=())
        else:
            ids[n] = tid
            st = reg.status_of(tid)
            if st != "active":
                inactive[n] = st
    return Resolution(ids, unknown, inactive)
