import streamlit as st
import pandas as pd
import numpy as np
import datetime as dt

df = pd.read_csv('fall_schedule_25.csv')

df.index.name = None
df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%Y').dt.strftime(%Y=%m-%d)

team_filter = st.multiselect(
    'Filter by Team'
    options=df['Team'].unique()
)

filtered_df = df[df['Team'].isin(team_filter)]
st.dataframe(filtered_df)
