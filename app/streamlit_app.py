import streamlit as st

st.set_page_config(page_title="KHL ELO", layout="wide")

pg = st.navigation([
    st.Page("pages/rankings.py", title="KHL ELO", icon=":material/line_axis:", default=True),
    st.Page("pages/upcoming.py", title="Upcoming Games", icon=":material/event:"),
    st.Page("pages/teams.py", title="Team History", icon=":material/groups:"),
    st.Page("pages/about.py", title="What is ELO?", icon=":material/help:"),
])
pg.run()
