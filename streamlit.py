"""Entry point for the deployed app (Streamlit Cloud's main file is streamlit.py).

The app itself lives in app/streamlit_app.py; this just runs it.
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "app" / "streamlit_app.py"), run_name="__main__")
