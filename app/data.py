"""Cached loaders for the Streamlit app. Reads only generated outputs + frozen legacy files."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from khl_elo.config import Season, load_seasons
from khl_elo.divisions import division_sort_key
from khl_elo.ingest import clean_name
from khl_elo.registry import Registry

DEFAULT_METHOD = "v1"


def seasons() -> list[Season]:
    """Seasons that have something to show, newest first."""
    out = []
    for s in load_seasons():
        if s.legacy or (s.output_dir(DEFAULT_METHOD) / "ratings.csv").exists():
            out.append(s)
    return sorted(out, key=lambda s: -s.index)


def _mtime_key(s: Season) -> float:
    p = s.legacy_ratings if s.legacy else s.output_dir(DEFAULT_METHOD) / "ratings.csv"
    return p.stat().st_mtime if p and p.exists() else 0.0


@st.cache_data(show_spinner=False)
def _load(season_id: str, _mtime: float) -> dict:
    s = next(x for x in load_seasons() if x.id == season_id)
    if s.legacy:
        tg = pd.read_csv(s.legacy_team_games)
        tg["Date"] = pd.to_datetime(tg["Date"], format="mixed")
        r = pd.read_csv(s.legacy_ratings, dtype={"Div": str})
        r["Team"] = r["Team"].map(clean_name)
        tg["Team"] = tg["Team"].map(clean_name)
        tg["Opponent"] = tg["Opponent"].map(clean_name)
        div = (r.groupby("Div")["ELO"].agg(Teams="size", ELO="mean", StDev="std").round(0).reset_index())
        leaders = r.sort_values("ELO", ascending=False).drop_duplicates("Div").set_index("Div")["Team"]
        div["Leader"] = div["Div"].map(leaders)
        meta = {"season_label": s.label, "method": "legacy-v0",
                "method_description": "Original scripts (K=75, scale 400, S − Win% update)",
                "last_game": tg["Date"].max().strftime("%Y-%m-%d"), "games_played": len(tg) // 2}
        preds = pd.DataFrame()
    else:
        d = s.output_dir(DEFAULT_METHOD)
        tg = pd.read_csv(d / "team_games.csv", parse_dates=["Date"], dtype={"Div": str, "Opp Div": str})
        r = pd.read_csv(d / "ratings.csv", dtype={"Div": str})
        div = pd.read_csv(d / "divisions.csv", dtype={"Div": str})
        preds = pd.read_csv(d / "predictions.csv", parse_dates=["Date"])
        meta = json.loads((d / "run_meta.json").read_text())
    div = div.iloc[sorted(range(len(div)), key=lambda i: division_sort_key(div["Div"].iat[i]))].reset_index(drop=True)
    return {"team_games": tg, "ratings": r, "divisions": div, "predictions": preds, "meta": meta, "legacy": s.legacy}


def load(season: Season) -> dict:
    return _load(season.id, _mtime_key(season))


@st.cache_data(show_spinner=False)
def _registry(_key: float) -> Registry:
    return Registry.load()


def registry() -> Registry:
    from khl_elo.config import REGISTRY_DIR

    p = REGISTRY_DIR / "teams.csv"
    return _registry(p.stat().st_mtime if p.exists() else 0.0)


def _games_for(tg: pd.DataFrame, team_id: str, season_id: str) -> pd.DataFrame:
    if "team_id" in tg.columns:
        return tg.loc[tg["team_id"] == team_id]
    reg = registry()
    names = {n for n in tg["Team"].unique() if reg.resolve(n, season_id) == team_id}
    return tg.loc[tg["Team"].isin(names)]


def team_timeline(team_id: str) -> pd.DataFrame:
    """Every game for one team across all seasons (legacy names mapped via the registry).

    Seasons the team spent as part of a merged team (lineage.csv) are included and labelled.
    """
    reg = registry()
    combined_ids = reg.lineage.loc[reg.lineage["part_id"] == team_id, "combined_id"].tolist()
    frames = []
    for s in sorted(seasons(), key=lambda x: x.index):
        tg = load(s)["team_games"]
        sub = _games_for(tg, team_id, s.id)
        if len(sub):
            frames.append(sub.assign(Season=s.label, Legacy=s.legacy))
        for cid in combined_ids:
            sub = _games_for(tg, cid, s.id)
            if len(sub):
                frames.append(sub.assign(Season=f"{s.label} (as {reg.name_of(cid)})", Legacy=s.legacy))
    return pd.concat(frames, ignore_index=True).sort_values("Date") if frames else pd.DataFrame()


def season_picker() -> Season:
    """Sidebar season selector shared by all pages."""
    opts = seasons()
    labels = [f"{s.label}{'  (legacy)' if s.legacy else ''}" for s in opts]
    idx = st.session_state.get("season_idx", 0)
    choice = st.sidebar.selectbox("Season", range(len(opts)), index=min(idx, len(opts) - 1),
                                  format_func=lambda i: labels[i])
    st.session_state["season_idx"] = choice
    return opts[choice]


def legacy_notice(data: dict) -> None:
    if data["legacy"]:
        st.info(
            "This season was calculated with the **original method** (legacy-v0: K=75, scale 400, "
            "and an update that slightly favoured away teams). Ratings are not directly comparable "
            "with seasons from Fall 2026 onward.",
            icon=":material/history:",
        )
