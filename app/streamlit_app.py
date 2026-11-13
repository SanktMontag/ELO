import sys
from pathlib import Path

import streamlit as st

# Resolve pages and the shared `data` module relative to this file, so the app
# also works when started through the repo-root streamlit.py (Streamlit Cloud).
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

st.set_page_config(page_title="KHL ELO", layout="wide")

pg = st.navigation([
    st.Page(APP_DIR / "pages" / "rankings.py", title="KHL ELO", icon=":material/line_axis:", default=True),
    st.Page(APP_DIR / "pages" / "upcoming.py", title="Upcoming Games", icon=":material/event:"),
    st.Page(APP_DIR / "pages" / "teams.py", title="Team History", icon=":material/groups:"),
    st.Page(APP_DIR / "pages" / "about.py", title="What is ELO?", icon=":material/help:"),
])
pg.run()
