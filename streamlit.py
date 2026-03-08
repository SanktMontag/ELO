import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(layout="wide")

game_df = pd.read_csv('game_graph_fall_25.csv')
rank_df = pd.read_csv('output_ratings_fall_25.csv')

game_df.index.name = None
rank_df.index.name = None

game_df['Date'] = pd.to_datetime(game_df['Date'], format='%m/%d/%y').dt.strftime('%Y-%m-%d')

divisions = rank_df['Div'].unique()
div_rank_list = []

for i in divisions:
    average = rank_df[rank_df['Div'] == i]['ELO'].mean()
    st_dev = np.std(rank_df[rank_df['Div'] == i]['ELO'])
    new_row = {'Division':i, 'ELO':round(average), 'StDev':round(st_dev)}
    div_rank_list.append(new_row)
    
div_df = pd.DataFrame(div_rank_list)

top_teams_indices = rank_df.groupby('Div')['ELO'].idxmax()
top_teams_list = rank_df.loc[top_teams_indices, 'Team'].tolist()
top_team_df = game_df[game_df['Team'].isin(top_teams_list)]

st.title('KHL ELO Rankings', text_alignment='left')

col1, col2, col3 = st.columns([2,10,3], gap='small')
with st.container(width='stretch', height='content', horizontal="center"):
    with col1:
        st.header('Division ELO', text_alignment='left')
        st.dataframe(div_df, hide_index=True, height='content')
    with col2:
        st.header('Division Leaders', text_alignment='left')
        st.line_chart(top_team_df, x='Date', y='ELO Post Game', color='Team', height='stretch')
    with col3:
        st.header('Complete Rankings', text_alignment='left')
        st.dataframe(rank_df, hide_index=True, height=845)

st.write('---')

st.header('Team Filtered Data', text_alignment='left')
team_filter = st.multiselect(
        'Filter by Team',
        options=game_df['Team'].unique(),
        default='Orange Crush'
    )

filtered_game_df = game_df[game_df['Team'].isin(team_filter)]

with st.container(width='stretch', height=500, horizontal="center"):
    st.dataframe(filtered_game_df, hide_index=True, height='stretch', width="content")
    st.line_chart(filtered_game_df, x='Date', y='ELO Post Game', color='Team', height='stretch')