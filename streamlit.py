import streamlit as st

pg = st.navigation([st.Page("khl_elo.py", title="KHL ELO", icon=":material/line_axis:"), st.Page("elo_explained.py", title="What is ELO?", icon=":material/help:")])
pg.run()