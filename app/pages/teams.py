import streamlit as st

from data import registry, team_timeline

st.title("Team History")
st.caption("Follows a team across seasons and name changes using the team registry.")

reg = registry()
teams = reg.teams.sort_values("name")
labels = {r.team_id: f"{r.name}" + ("" if r.status == "active" else f"  ({r.status})") for r in teams.itertuples()}
tid = st.selectbox("Team", list(labels), format_func=labels.get)

row = teams.loc[teams["team_id"] == tid].iloc[0]
rel = reg.related(tid)
for link in rel.itertuples():
    if link.combined_id == tid:
        st.caption(f"Combined team in {link.season}, made up of **{reg.name_of(link.part_id)}**. {link.note}")
    else:
        st.caption(f"Played {link.season} as part of **{reg.name_of(link.combined_id)}**. {link.note}")
c1, c2, c3 = st.columns(3)
c1.metric("Status", row["status"].title())
c2.metric("First season (registry)", row["first_season"] or "—")
tl = team_timeline(tid)
c3.metric("Current ELO", int(tl["ELO Post Game"].iloc[-1]) if len(tl) else "—")

if len(tl):
    st.line_chart(tl, x="Date", y="ELO Post Game", color="Season", height=380)
    if tl["Legacy"].any():
        st.caption("Seasons before Fall 2026 were calculated with the original method.")
    with st.expander("All games"):
        st.dataframe(tl[["Season", "Date", "Team", "Opponent", "GF", "GA", "Result", "+/- ELO", "ELO Post Game"]],
                     hide_index=True, column_config={"Date": st.column_config.DateColumn(format="YYYY-MM-DD")})
else:
    st.write("No games found for this team yet.")

names = reg.aliases.loc[reg.aliases["team_id"] == tid, ["alias", "from_season", "to_season"]]
events = reg.events.loc[reg.events["team_id"] == tid, ["date", "season", "event", "detail"]]
a, b = st.columns(2)
with a:
    st.subheader("Names")
    st.dataframe(names.rename(columns={"alias": "Name", "from_season": "From", "to_season": "To"}), hide_index=True)
with b:
    st.subheader("Events")
    st.dataframe(events, hide_index=True)
