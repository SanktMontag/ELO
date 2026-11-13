import pandas as pd
import streamlit as st

from data import legacy_notice, load, season_picker

season = season_picker()
data = load(season)
meta, tg, ratings, divs = data["meta"], data["team_games"], data["ratings"], data["divisions"]

st.title(f"KHL ELO Rankings — {meta['season_label']}")
if meta.get("last_game"):
    d = pd.to_datetime(meta["last_game"])
    last = f"{d.month}/{d.day}/{d:%y}"
else:
    last = "—"
st.caption(f"Through {last} · {meta.get('games_played', 0)} games · method `{meta['method']}`")
legacy_notice(data)

col1, col2, col3 = st.columns([3, 9, 4], gap="small")
with col1:
    st.subheader("Division ELO")
    st.dataframe(divs[["Div", "ELO", "StDev"]], hide_index=True,
                 column_config={"ELO": st.column_config.NumberColumn(format="%d"),
                                "StDev": st.column_config.NumberColumn(format="%d")})
with col2:
    st.subheader("Division Leaders")
    leaders = divs["Leader"].dropna().tolist()
    lead_tg = tg.loc[tg["Team"].isin(leaders)]
    st.line_chart(lead_tg, x="Date", y="ELO Post Game", color="Team", height=520)
with col3:
    st.subheader("Complete Rankings")
    div_opts = divs["Div"].tolist()
    pick = st.multiselect("Division", div_opts, placeholder="All divisions", label_visibility="collapsed")
    view = ratings if not pick else ratings.loc[ratings["Div"].isin(pick)]
    cols = [c for c in ["Ranking", "Team", "Div", "ELO", "GP", "W", "L", "T", "Season +/-"] if c in view.columns]
    st.dataframe(view[cols], hide_index=True, height=520,
                 column_config={"Season +/-": st.column_config.NumberColumn(format="%+d")})

st.divider()
st.header("Team Filtered Data")
teams = sorted(tg["Team"].unique())
default = [t for t in ("Orange Crush",) if t in teams] or teams[:1]
team_filter = st.multiselect("Filter by Team", options=teams, default=default)
f = tg.loc[tg["Team"].isin(team_filter)].sort_values(["Team", "Date"])

left, right = st.columns([3, 2])
with left:
    show = [c for c in ["Date", "Team", "ELO", "Opponent", "Opp ELO", "Win %", "Tie %", "Loss %",
                        "GF", "GA", "Result", "+/- ELO", "ELO Post Game"] if c in f.columns]
    st.dataframe(f[show], hide_index=True, height=420,
                 column_config={"Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                                "+/- ELO": st.column_config.NumberColumn(format="%+d")})
with right:
    st.line_chart(f, x="Date", y="ELO Post Game", color="Team", height=420)
