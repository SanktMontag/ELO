import streamlit as st

from data import load, season_picker

season = season_picker()
data = load(season)
st.title(f"Upcoming Games — {data['meta']['season_label']}")

preds = data["predictions"]
if data["legacy"] or preds.empty:
    st.write("No upcoming games in the latest schedule export for this season.")
    st.stop()

st.caption("Win/Tie/Loss chances come from current ratings. They're estimates, not guarantees.")
teams = sorted(set(preds["Away"]) | set(preds["Home"]))
pick = st.multiselect("Team", teams, placeholder="All teams")
view = preds if not pick else preds.loc[preds["Away"].isin(pick) | preds["Home"].isin(pick)]
st.dataframe(
    view.drop(columns=["game_id"]),
    hide_index=True,
    column_config={
        "Date": st.column_config.DateColumn(format="ddd MMM D"),
        "Away Win %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
        "Tie %": st.column_config.NumberColumn(format="%.0f%%"),
        "Home Win %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
    },
)
