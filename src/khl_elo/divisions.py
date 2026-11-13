"""Parse Kraken division labels and work out each team's current division.

A team's current division is the label on its most recent game, verbatim -
combined groupings like "10A-B" are real divisions, not noise.

Label shapes seen in the Kraken export:
    "Division 1"          -> tier 1, no letter
    "Division 6C"         -> tier 6, letter C
    "Division 6"          -> bare tier: early-season placeholder, or ambiguous if it is a
                             team's latest label and tier 6 has lettered divisions
    "Division 6C,6D,7A"   -> crossover grouping                     (combined)
    "Division 10A-B"      -> crossover grouping                     (combined)
    "40+ Fall 26", "Women's Division Fall 26"  -> not a ladder division (ignored)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import DATA_DIR

LADDER_RE = re.compile(r"^\s*Division\s+(\d+)\s*(.*?)\s*$", re.IGNORECASE)
SINGLE_RE = re.compile(r"^(\d+)([A-Z]?)$")


@dataclass(frozen=True)
class DivisionLabel:
    raw: str
    code: str            # label without the "Division " prefix, e.g. "6C", "6", "6C,6D,7A"
    tier: int
    letter: str | None   # None if no single letter
    combined: bool       # multiple divisions in one label

    @property
    def single(self) -> bool:
        return not self.combined


def is_ladder(label: object) -> bool:
    return isinstance(label, str) and LADDER_RE.match(label) is not None


def parse_label(label: str) -> DivisionLabel | None:
    """Parse a raw division label; returns None for non-ladder labels."""
    if not isinstance(label, str):
        return None
    m = LADDER_RE.match(label)
    if not m:
        return None
    tier = int(m.group(1))
    rest = m.group(2).upper().replace(" ", "")
    code = f"{tier}{rest}"
    single = SINGLE_RE.match(code)
    if single:
        letter = single.group(2) or None
        return DivisionLabel(raw=label, code=code, tier=tier, letter=letter, combined=False)
    return DivisionLabel(raw=label, code=code, tier=tier, letter=None, combined=True)


def division_sort_key(code: str) -> tuple[int, str]:
    """Ladder order: 1 < 2 < 3A < 3B < ... < 10B. Unknown codes sort last."""
    m = SINGLE_RE.match(str(code).upper())
    if not m:
        m2 = re.match(r"^(\d+)", str(code))
        return (int(m2.group(1)) if m2 else 999, "~")
    return (int(m.group(1)), m.group(2))


def lettered_divisions(labels) -> dict[int, set[str]]:
    """{tier: {"3A", "3B", ...}} for every single lettered division code in `labels`
    (raw labels like "Division 3B" or bare codes like "3B")."""
    out: dict[int, set[str]] = {}
    for lab in labels:
        if not isinstance(lab, str) or not lab:
            continue
        p = parse_label(lab if lab.lower().startswith("division") else f"Division {lab}")
        if p and p.single and p.letter:
            out.setdefault(p.tier, set()).add(p.code)
    return out


# ------------------------------------------------------------------ confirmations

CONFIRM_COLS = ["team_id", "team", "label", "division", "confirmed_at"]


def confirm_path(season_id: str) -> Path:
    return DATA_DIR / "divisions" / f"{season_id}.csv"


def load_confirmed(season_id: str) -> dict[str, tuple[str, str]]:
    """{team_id: (label code it was confirmed against, division)}."""
    path = confirm_path(season_id)
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return {r.team_id: (r.label, r.division) for r in df.itertuples()}


def save_confirmation(season_id: str, team_id: str, team: str, label: str, division: str) -> None:
    path = confirm_path(season_id)
    df = (pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists()
          else pd.DataFrame(columns=CONFIRM_COLS))
    df = df.loc[df["team_id"] != team_id].reset_index(drop=True)
    df.loc[len(df)] = [team_id, team, label, division, f"{datetime.now():%Y-%m-%d %H:%M}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values("team").to_csv(path, index=False)


# ------------------------------------------------------------------ resolution

@dataclass
class DivisionPick:
    team_id: str
    division: str
    latest: str               # code on the team's most recent game ("" if none)
    source: str               # label | confirmed | unconfirmed | fallback
    candidates: list[str]     # for unconfirmed picks: the lettered divisions of that tier
    history: list[tuple]      # (code, games, first date, last date), oldest first
    recent_opponents: list[str]  # opponents' team_ids in games under the latest label, newest first


def resolve_divisions(
    team_rows: pd.DataFrame,
    fallback: dict[str, str] | None = None,
    confirmed: dict[str, tuple[str, str]] | None = None,
) -> dict[str, DivisionPick]:
    """Work out each team's current division.

    team_rows needs columns team_id, division_label, order (higher = more recent);
    optional `date` and `opp_id` columns add context for prompts.

    The source of truth is the team's own label on its most recent game (played or
    scheduled), taken as-is: Kraken uses odd crossover groupings mid-season such as
    "10A-B" or "6D/7A", and early-season games carry a bare tier ("Division 9")
    before the split.

    Exception: a bare tier on the latest game while that tier is lettered (e.g.
    "Division 3" when 3A/3B exist) is ambiguous - the website export is not
    consistent. Such picks need a confirmation (`khl divisions confirm`); until
    then the previous/seed division is used if it is in that tier.

    A confirmation (or manual override) holds while the team's latest label stays
    the one it was confirmed against; a different label from a later import wins.
    """
    fallback = fallback or {}
    confirmed = confirmed or {}
    lettered = lettered_divisions(list(team_rows["division_label"].dropna().unique()) + list(fallback.values()))
    has_date = "date" in team_rows.columns
    has_opp = "opp_id" in team_rows.columns
    picks: dict[str, DivisionPick] = {}
    for team_id, grp in team_rows.sort_values("order", kind="stable").groupby("team_id", sort=False):
        ladder = [(p, i) for i, l in enumerate(grp["division_label"].tolist()) if (p := parse_label(l))]
        history: dict[str, list] = {}
        for p, i in ladder:
            d = grp["date"].iat[i] if has_date else None
            h = history.setdefault(p.code, [p.code, 0, d, d])
            h[1] += 1
            h[3] = d
        hist = [tuple(h) for h in history.values()]
        if not ladder:
            prev = str(fallback.get(team_id) or "")
            picks[team_id] = DivisionPick(team_id, prev or "?", "", "fallback", [], hist, [])
            continue
        last, _ = ladder[-1]
        opps = [grp["opp_id"].iat[i] for p, i in reversed(ladder) if p.code == last.code] if has_opp else []
        conf = confirmed.get(team_id)
        if conf and conf[0] == last.code:
            pick = DivisionPick(team_id, conf[1], last.code, "confirmed", [], hist, opps)
        elif last.single and last.letter is None and last.tier in lettered:
            cands = sorted(lettered[last.tier], key=division_sort_key)
            prev = str(fallback.get(team_id) or "")
            div = prev if prev in cands else last.code
            pick = DivisionPick(team_id, div, last.code, "unconfirmed", cands, hist, opps)
        else:
            pick = DivisionPick(team_id, last.code, last.code, "label", [], hist, opps)
        picks[team_id] = pick
    return picks


def current_divisions(
    team_rows: pd.DataFrame,
    fallback: dict[str, str] | None = None,
    confirmed: dict[str, tuple[str, str]] | None = None,
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """({team_id: division}, {team_id: (review kind, detail)}). See resolve_divisions."""
    picks = resolve_divisions(team_rows, fallback, confirmed)
    return {t: p.division for t, p in picks.items()}, pick_flags(picks)


def pick_flags(picks: dict[str, DivisionPick]) -> dict[str, tuple[str, str]]:
    """{team_id: (review kind, detail)} for picks that need a look."""
    flags: dict[str, tuple[str, str]] = {}
    for t, p in picks.items():
        if p.source == "fallback":
            flags[t] = ("division_fallback", f"no ladder division label; kept previous division {p.division}"
                        if p.division != "?" else "no ladder division label; no previous division known")
        elif p.source == "unconfirmed":
            flags[t] = ("division_unconfirmed",
                        f"latest label 'Division {p.latest}' is ambiguous ({'/'.join(p.candidates)}); "
                        f"using {p.division} until confirmed")
    return flags
