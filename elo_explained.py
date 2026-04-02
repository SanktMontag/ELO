import streamlit as st

text1 = '''# What is ELO?

ELO is a rating system originally developed to rank chess players based on their relative skill level.  Named for the creator chessmaster Arpad Elo it has been adapted for many sports to rank teams.

### TL:DR

Each team has an ELO rating and each game is a net zero result.  If Team A defeats Team B, some of Team B's rating goes to Team A.  Think of it as an ante game like marbles (or pogs for the millenial crowd).  Win as a favorite you win less, win as a underdog you win more.

### But Why?

For fun, that's why... I don't think it requires much more explanation.  For the same reason we keep score, have standings, stats, etc.  I like data and trying to rationalize things with that data.  Are we getting better?  Do we struggle against a certain team? etc.  By all means, if it's not your bag feel free to ignore me.  This is a side project that is not endorsed by the league.

### So How Does it Work?

The nuts and bolts of it all... Well the simplest place to start is the base ratings.  Each team enters the game with a rating, Team A: Ra, Team B: Rb.  The expected outcome E is based on a comparison of Ra and Rb with a base and scale factor.  For this implementation, base 10 and a scale factor of 400.    

Thus the expected outcome for Team A, a win over Team B is calculated as:

'''
st.markdown(text1)

st.image("assets/2026-04-01-21-55-38-image.png")

st.markdown("That can be simplified a bit to make the math easier to a Q value")

st.image("assets/2026-04-01-21-57-08-image.png")

st.image("assets/2026-04-01-21-57-33-image.png")

st.markdown("If one team wins the other must have lost so the sum must be 1")

st.image("assets/2026-04-01-21-58-50-image.png")


st.markdown("But what about that base and scale factor?  Well in effect it means that for every 400 points of difference in the ratings, that represents a 10x difference in expected outcome.")

st.markdown("Great so Team A beats Team B, now what?  We calculate a posterior rating!  Take the rating at the game start, Ra (also called the prior rating) and add something to it.  How many points are traded between the teams is based on the result S, the expected outcome E,  and a factor K.")

st.image("assets/2026-04-01-22-05-21-image.png")

st.markdown("K can be thought of as a rate of change.  The newer or unpredictable the higher the K.  Normaly this value is between 40 and 10.  Given how quickly things change the K used in this implementation is 75.  It is actually modified with a factor based on the goal differential but set that aside for now.  I'll come back to it...")

st.markdown("Example time...")

st.markdown("Team A has an ELO of 1200, Team B an ELO of 1000.  A defeats B... what happens?")

st.image("assets/2026-04-01-22-16-43-image.png")

st.markdown("Team A gains 18 points towards their rating.  But what about if Team B wins?")

st.image("assets/2026-04-01-22-19-22-image.png")

st.markdown("Team B would take 57 points because they were much less likely to win!")

st.markdown("Thats the simple bit of it all...  For this specific implementation I also consider a third outcome, ties as well as account for the degree of victory by using goal differential.")

st.markdown("To be continued...")