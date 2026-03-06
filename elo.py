import pandas as pd
import numpy as np
from dateutil.parser import *
from dateutil.tz import *
from datetime import *

def find_value_index(df, column_name, value):
    return df.index[df[column_name] == value].astype('int64').tolist()

df = pd.read_csv("fall_schedule_25.csv")

for i, _ in enumerate(df.index):

    if np.isnan(df.at[i, "Away Score"]) == True:
        df = df.drop([i])
    
df = df.reset_index()

remove = ["40+ Advanced White",
          "40+ Advanced Sky Blue",
          "40+ Advanced Green",
          "40+ Advanced Orange",
          "40+ Advanced Grey",
          "40+ Advanced Black",
          "40+ Advanced Red",
          "40+ Grey",
          "40+ Red",
          "40+ White",
          "40+ Sky Blue",
          "40+ Royal",
          "40+ Yellow",
          "40+ Orange",
          "40+ Navy",
          "Black Sheesh",
          "Blue Footed Bloobies",
          "Grey Dust Bunnies",
          "Pineapple Express",
          "Red Hots",
          "White Yetis",
          "Isotopes-Cascade",
          "Razor Clams - Cascade",
          "Warriors - Cascade",
          "Grizzlies-Cascade",
          "Tigers-Cascade",
          "Cascade Lumberjacks-Cascade",
          "Lumberjacks-Cascade",
          "Wolverines-Cascade",
          "United-Cascade",
          "Kelly Days-Cascade",
          "Fighting Saints-Cascade",
          "Coppernails-Cascade",
          "Women''s Yellow",
          "Women''s Green",
          "Women''s White",
          "Women''s Orange",
          "Women''s Sky Blue",
          "Women''s Pink",
          "Women''s Red",
          "Women''s Purple",
          "Women''s #7",
          "Women''s #8",
          '40+ Advanced Baines',
          '40+ Advanced Puck Hogs',
          '40+ Advanced 40 Proof',
          '40+ Advanced Bakers Dozen',
          '40+ Advanced Falk',
          '40+ Advanced Gritty Pylons',
          '40+ Assisted Living',
          '40+ Puck Dynasty',
          '40+ Swift',
          '40+ Mid-Ice Crisis',
          '40+ Rough Draft',
          '40+ Red Flags',
          '40+ Keller',
          '40+ Carls Seniors',
          '40+ Coldtimers',
          '40+ Elder Skatesmen',
          '40+ Geri Hat Tricks',
          '40+ Carl''s Seniors',
          '40+ Gritty Pylons',
          'Rink Flamingos',
          'Black Sheep-Cascade',
          '40+ Advanced Gratiot',
          '40+ Advanced Tagami',
          '40+ Carl''s Seniors',
          '40+ Rusty Blades',            
          ]

a_result_dict = {0:'Loss',0.5:'Tie',1:'Win'}
b_result_dict = {0:'Loss',0.5:'Tie',1:'Win'}

for i, _ in enumerate(df.index):
    if df.at[i, "Away Team"] in remove or df.at[i, "Home Team"] in remove:
        df = df.drop([i])

df = df.reset_index()

df["Game_ID"] = ""

for i, _ in enumerate(df.index):
    df.at[i,"Date"] = parse(df.at[i,"Date"])
    df.at[i,"Date"] = datetime.strftime(df.at[i,"Date"], "%m/%d/%y")
    d = df.at[i,"Date"]
    df.at[i, "Game_ID"] = d + "_" + df.at[i,"Away Team"] + "_@_" + df.at[i,"Home Team"]

df.drop('level_0', axis=1, inplace=True)
df.drop('index', axis=1, inplace=True)
df.drop('Game#', axis=1, inplace=True)
df["Away Score"] = df["Away Score"].astype("Int64")
df["Home Score"] = df["Home Score"].astype("Int64")
df["Away ELO Prior"] = 0
df["Away ELO Prior"] = df["Away ELO Prior"].astype("float64")
df["Away EA"] = 0
df["Away ELO Posterior"] = 0
df["Away ELO Posterior"] = df["Away ELO Posterior"].astype("float64")
df["Away Delta"] = 0
df["Home ELO Prior"] = 0
df["Home ELO Prior"] = df["Home ELO Prior"].astype("float64")
df["Home EA"] = 0
df["Home ELO Posterior"] = 0
df["Home ELO Posterior"] = df["Home ELO Posterior"].astype("float64")
df["Home Delta"] = 0

initial_ratings = pd.read_csv("Initial_25_Fall.csv")
live_ratings = initial_ratings

df_game_graph = pd.DataFrame()

for i, _ in enumerate(df.index):
    a = df.at[i,"Away Team"]
    a_score = df.at[i,"Away Score"]
    b = df.at[i,"Home Team"]
    b_score = df.at[i,"Home Score"]

    print(a, " ", b)

    a_live_reference_index = find_value_index(live_ratings, "Team", a)[0]
    a_full_name = live_ratings.at[a_live_reference_index,"Team"]
    a_elo_prior = live_ratings.at[a_live_reference_index,"ELO"]

    df.at[i,"Away ELO Prior"] = live_ratings.at[a_live_reference_index,"ELO"]

    b_live_reference_index = find_value_index(live_ratings, "Team", b)[0]
    b_full_name = live_ratings.at[b_live_reference_index,"Team"]
    b_elo_prior = live_ratings.at[b_live_reference_index,"ELO"]
    
    df.at[i,"Home ELO Prior"] = live_ratings.at[b_live_reference_index,"ELO"]

    Qa = 10**(a_elo_prior/400)
    Qb = 10**(b_elo_prior/400)
    EA_a = Qa / (Qa + Qb)
    EA_b = Qb / (Qa + Qb)

    df.at[i,"Away EA"] = round(EA_a * 100,1)
    df.at[i,"Home EA"] = round(EA_b * 100,1)

    r = 0.888

    Wa = r*(EA_a*(1-EA_a))+EA_a**2
    Da = 2*(EA_a-Wa)
    La = 1-Wa-Da

    Wb = r*(EA_b*(1-EA_b))+EA_b**2
    Db = 2*(EA_b-Wb)
    Lb = 1-Wb-Db

    gd = abs(a_score-b_score)
    ka = 75

    kmod_map = {
        1: 1,
        2: 1.5,
        3: 1.75,
        4: 1.875,
        5: 2,
        6: 2.125,
        7: 2.25,
        8: 2.375,
        9: 2.5,
        10: 2.625,
        11: 2.75,
        12: 2.875,
        13: 3,
        14: 3.125,
        15: 3.25,
    }
    
    kmod = kmod_map.get(gd, 1)

    if a_score > b_score:
        SA_a = 1
        SA_b = 0
    elif a_score < b_score:
        SA_a = 0
        SA_b = 1
    else:
        SA_a = 0.5
        SA_b = 0.5
   
    a_elo_post = a_elo_prior + (ka*kmod) * (SA_a - Wa)
    a_delta = a_elo_post - a_elo_prior
    b_elo_post = b_elo_prior - a_delta

    live_ratings.at[a_live_reference_index,"ELO"] = a_elo_post
    df.at[i,"Away ELO Posterior"] = live_ratings.at[a_live_reference_index,"ELO"]

    live_ratings.at[b_live_reference_index,"ELO"] = b_elo_post
    df.at[i,"Home ELO Posterior"] = live_ratings.at[b_live_reference_index,"ELO"]

    away_record = pd.Series({'Date':df.at[i,'Date'],'Team':a_full_name, 'ELO':round(a_elo_prior), 'Opponent':b_full_name, 'Opp ELO':round(b_elo_prior), 'Delta':round(a_elo_prior-b_elo_prior),
                             'Win %':round(Wa * 100,1), 'Tie %':round(Da * 100,1), 'Loss %':round(La * 100,1), 'GF':a_score, 'GA':b_score,
                             'Result':a_result_dict.get(SA_a), '+/- ELO':round(a_elo_post-a_elo_prior)})
    df_game_graph = pd.concat([df_game_graph, away_record.to_frame().T], ignore_index=True)

    home_record = pd.Series({'Date':df.at[i,'Date'],'Team':b_full_name, 'ELO':round(b_elo_prior), 'Opponent':a_full_name, 'Opp ELO':round(a_elo_prior), 'Delta':round(b_elo_prior-a_elo_prior),
                             'Win %':round(Wb * 100,1), 'Tie %':round(Db * 100,1), 'Loss %':round(Lb * 100,1), 'GF':b_score, 'GA':a_score,
                             'Result':b_result_dict.get(SA_b), '+/- ELO':round(b_elo_post-b_elo_prior)})
    df_game_graph = pd.concat([df_game_graph, home_record.to_frame().T], ignore_index=True)

live_ratings["ELO"] = live_ratings["ELO"].astype('int64')
live_ratings = live_ratings.sort_values("ELO", ascending=False)
live_ratings = live_ratings.reset_index(drop=True)
live_ratings['Ranking'] = live_ratings.index + 1
live_ratings = live_ratings[['Ranking', 'Team', 'Div', 'ELO']]

df["Away ELO Prior"] = round(df["Away ELO Prior"]).astype("Int64")
df["Away ELO Posterior"] = round(df["Away ELO Posterior"]).astype("Int64")
df["Away Delta"] = df["Away ELO Posterior"] - df["Away ELO Prior"]
df["Home ELO Prior"] = round(df["Home ELO Prior"]).astype("Int64")
df["Home ELO Posterior"] = round(df["Home ELO Posterior"]).astype("Int64")
df["Home Delta"] = df["Home ELO Posterior"] - df["Home ELO Prior"]

print(live_ratings.to_string(index=False))

df.to_csv("output_gamelog_fall_25.csv")
live_ratings.to_csv("output_ratings_fall_25.csv")
df_game_graph.to_csv("game_graph_fall_25.csv")