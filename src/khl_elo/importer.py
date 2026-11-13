"""Merge a Kraken schedule export into a season's schedule ledger.

`data/raw/schedules/<season>.csv` is the season ledger: every game seen in any
export for that season, in one normalised format. An export can cover any
window (a week, a month, the whole season); importing it:

  * adds games that are new
  * updates existing games (scores filled in, score corrections, time/arena/division changes)
  * matches games by Kraken game ID (from the Scoresheet/Preview URL) when available,
    otherwise by date + away team + home team
  * moves a game when the same Kraken ID appears on a new date (reschedule)
  * removes *unplayed* ledger games inside the export's date range that the export no longer
    lists (cancelled or rescheduled without an ID), unless prune=False
  * never deletes or blanks out a played game; such cases are reported instead

A copy of every imported file is kept in data/raw/imports/<season>/ for audit.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, get_season
from .ingest import clean_name, name_key, parse_dates

LEDGER_COLS = ["Kraken ID", "Date", "Time", "Arena", "Away Team", "Away Score", "Home Team", "Home Score",
               "Away Division", "Home Division", "Game Type", "Scoresheet"]
UPDATABLE = ["Time", "Arena", "Away Division", "Home Division", "Game Type", "Scoresheet"]
_ID_RE = re.compile(r"/(?:scoresheet|game)/(\d+)")


@dataclass
class ImportReport:
    added: list[str] = field(default_factory=list)
    scored: list[str] = field(default_factory=list)
    corrected: list[str] = field(default_factory=list)
    rescheduled: list[str] = field(default_factory=list)
    detail_updates: int = 0
    pruned: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unchanged: int = 0
    window: tuple[str, str] | None = None
    ledger_games: int = 0
    backup: Path | None = None

    @property
    def changed(self) -> bool:
        return bool(self.added or self.scored or self.corrected or self.rescheduled or self.pruned
                    or self.detail_updates)


def _kraken_id(row: pd.Series) -> str:
    for col in ("Kraken ID", "Scoresheet", "Preview"):
        v = row.get(col)
        if isinstance(v, str) and v:
            if col == "Kraken ID":
                return v.strip()
            m = _ID_RE.search(v)
            if m:
                return m.group(1)
    return ""


def normalise_export(path: Path) -> pd.DataFrame:
    """Read any Kraken export (old or new layout) into LEDGER_COLS."""
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    need = ["Date", "Away Team", "Home Team", "Away Division", "Home Division"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}. Is this a Kraken schedule export?")
    out = pd.DataFrame({c: df[c] if c in df.columns else "" for c in LEDGER_COLS})
    out["Kraken ID"] = df.apply(_kraken_id, axis=1)
    dates = parse_dates(df["Date"])
    bad = dates.isna()
    if bad.any():
        raise ValueError(f"{path.name}: unreadable dates {df.loc[bad, 'Date'].unique()[:5].tolist()}")
    out["Date"] = dates.dt.strftime("%Y-%m-%d")
    for c in ("Away Team", "Home Team", "Away Division", "Home Division", "Arena"):
        out[c] = out[c].map(lambda v: clean_name(v) if v else "")
    for c in ("Away Score", "Home Score"):
        out[c] = out[c].str.strip()
    return out.fillna("")


def _key(row) -> str:
    return f"{row['Date']}|{name_key(row['Away Team'])}|{name_key(row['Home Team'])}"


def _label(row) -> str:
    score = f" {row['Away Score']}-{row['Home Score']}" if row["Away Score"] != "" else ""
    return f"{row['Date']} {row['Away Team']} @ {row['Home Team']}{score}"


def _played(row) -> bool:
    return row["Away Score"] != "" and row["Home Score"] != ""


def load_ledger(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=LEDGER_COLS)
    return normalise_export(path)


def import_export(season_id: str, export_path: Path, prune: bool = True, dry_run: bool = False) -> ImportReport:
    season = get_season(season_id)
    if season.legacy:
        raise ValueError(f"{season_id} is a legacy season; its data is frozen")
    if season.schedule is None:
        raise ValueError(f"Season {season_id} has no `schedule` path in seasons.toml")
    export_path = Path(export_path)
    new = normalise_export(export_path)
    ledger = load_ledger(season.schedule).reset_index(drop=True)
    rep = ImportReport()
    if new.empty:
        rep.warnings.append("export contains no games")
        return rep
    rep.window = (new["Date"].min(), new["Date"].max())

    dup = new.duplicated(subset=["Date", "Away Team", "Home Team", "Arena", "Kraken ID"])
    if dup.any():
        rep.warnings.append(f"{dup.sum()} duplicate rows inside the export ignored")
        new = new.loc[~dup]

    by_id = {kid: i for i, kid in ledger["Kraken ID"].items() if kid}
    by_key: dict[str, list[int]] = {}
    for i, row in ledger.iterrows():
        by_key.setdefault(_key(row), []).append(i)

    touched: set[int] = set()
    for _, row in new.iterrows():
        idx = by_id.get(row["Kraken ID"]) if row["Kraken ID"] else None
        if idx is None:
            cands = [i for i in by_key.get(_key(row), []) if i not in touched]
            # prefer a candidate with no Kraken ID or the same one
            cands = [i for i in cands if ledger.at[i, "Kraken ID"] in ("", row["Kraken ID"])]
            idx = cands[0] if cands else None
        if idx is None:
            ledger.loc[len(ledger)] = row
            touched.add(len(ledger) - 1)
            rep.added.append(_label(row))
            continue
        touched.add(idx)
        old = ledger.loc[idx].copy()
        changed = False
        if row["Kraken ID"] and not old["Kraken ID"]:
            ledger.at[idx, "Kraken ID"] = row["Kraken ID"]
        if (row["Date"], name_key(row["Away Team"]), name_key(row["Home Team"])) != (
                old["Date"], name_key(old["Away Team"]), name_key(old["Home Team"])):
            if _played(old) and not _played(row):
                rep.warnings.append(f"played game {_label(old)} now listed unplayed as {_label(row)}; kept as played")
                continue
            for c in ("Date", "Away Team", "Home Team"):
                ledger.at[idx, c] = row[c]
            rep.rescheduled.append(f"{_label(old)}  ->  {row['Date']} {row['Away Team']} @ {row['Home Team']}")
            changed = True
        if _played(row):
            if not _played(old):
                rep.scored.append(_label(row))
                changed = True
            elif (row["Away Score"], row["Home Score"]) != (old["Away Score"], old["Home Score"]):
                rep.corrected.append(f"{_label(old)}  ->  {row['Away Score']}-{row['Home Score']}")
                changed = True
            ledger.at[idx, "Away Score"] = row["Away Score"]
            ledger.at[idx, "Home Score"] = row["Home Score"]
        elif _played(old):
            rep.warnings.append(f"export has no score for {_label(old)}; kept existing score")
        detail = False
        for c in UPDATABLE:
            if row[c] and row[c] != old[c]:
                ledger.at[idx, c] = row[c]
                detail = True
        if detail and not changed:
            rep.detail_updates += 1
        if not changed and not detail:
            rep.unchanged += 1

    # Unplayed ledger games inside the export window that the export no longer lists.
    lo, hi = rep.window
    stale = [i for i in ledger.index
             if i not in touched and lo <= ledger.at[i, "Date"] <= hi]
    drop = []
    for i in stale:
        row = ledger.loc[i]
        if _played(row):
            rep.warnings.append(f"played game {_label(row)} is missing from the export; kept")
        elif prune:
            drop.append(i)
            rep.pruned.append(_label(row))
        else:
            rep.warnings.append(f"unplayed game {_label(row)} is missing from the export (cancelled?); kept (--no-prune)")
    ledger = ledger.drop(index=drop)

    # Sort chronologically; time within a day when known.
    t = pd.to_datetime(ledger["Time"], format="%I:%M %p", errors="coerce")
    ledger = (ledger.assign(_d=ledger["Date"], _t=t.dt.strftime("%H:%M").fillna(""))
              .sort_values(["_d", "_t"], kind="stable").drop(columns=["_d", "_t"]).reset_index(drop=True))
    rep.ledger_games = len(ledger)

    if not dry_run:
        arch = DATA_DIR / "raw" / "imports" / season_id
        arch.mkdir(parents=True, exist_ok=True)
        stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        rep.backup = arch / f"{stamp}_{export_path.name}"
        shutil.copy2(export_path, rep.backup)
        if rep.changed:
            if season.schedule.exists():
                shutil.copy2(season.schedule, arch / f"{stamp}_ledger_before.csv")
            season.schedule.parent.mkdir(parents=True, exist_ok=True)
            ledger[LEDGER_COLS].to_csv(season.schedule, index=False)
    return rep
