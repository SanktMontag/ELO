import streamlit as st

from khl_elo.methods import get_method

from khl_elo.config import SeasonRules

m = get_method("v1")
_rules = SeasonRules.from_config(m.cfg)
K, SCALE, D = int(m.k), int(m.scale), m.draw_factor

st.title("What is ELO?")
st.markdown(
    """
ELO is a rating system originally developed to rank chess players based on their relative skill level.
It's named for its creator, chess master Arpad Elo, and has been adapted for many sports to rank teams.

### TL;DR

Each team has an ELO rating, and every game is net zero. If Team A beats Team B, some of Team B's
rating goes to Team A. Think of it as an ante game like marbles (or pogs for the millennial crowd).
Win as a favorite and you win less; win as an underdog and you win more.

### But why?

For fun, that's why. For the same reason we keep score, standings and stats. I like data and trying to
rationalize things with it. Are we getting better? Do we struggle against a certain team? If it's not
your bag, feel free to ignore me. This is a side project and is not endorsed by the league.

### So how does it work?

Each team enters the game with a rating, Team A: $R_a$ and Team B: $R_b$. The **expected score** for
Team A compares the two ratings on a logistic curve:
"""
)
st.latex(rf"E_a = \frac{{1}}{{1 + 10^{{(R_b - R_a)/{SCALE}}}}}, \qquad E_b = 1 - E_a")
st.markdown(
    f"""
The **scale factor of {SCALE}** means that every {SCALE} points of difference is a 10× difference in odds.
(Before Fall 2026 this was 400. Testing on three seasons of KHL results showed 400 was too confident:
favorites won less often than predicted.)

After the game, each team's new rating is its old rating plus a share of the points on the table:
"""
)
st.latex(rf"R_a' = R_a + K \cdot G \cdot (S_a - E_a)")
st.markdown(
    f"""
* **S** is the result: 1 for a win, ½ for a tie, 0 for a loss.
* **K = {K}** is the rate of change. Chess uses 10–40; rec hockey rosters change fast, so it's higher here.
* **G** is the goal-differential multiplier: 1× for a one-goal game, 1.5× for two goals, 1.75× for three,
  then +0.125× per extra goal, capped at {m.gd_cap}×.

Team B gets exactly the opposite change, so the league total never inflates.
"""
)

st.markdown("### Example")
ra, rb = 1200, 1000
e = m.expected(ra, rb)
win = m.update(ra, rb, 3, 2).away_delta
upset = m.update(rb, ra, 3, 2).away_delta
st.markdown(
    f"""
Team A is rated {ra} and Team B is rated {rb}. Team A's expected score is **{e:.2f}**.

* A wins 3–2: A gains **{win:+.0f}** and B loses the same amount.
* B wins 3–2: B gains **{upset:+.0f}**, because they were much less likely to win.
"""
)

st.markdown("### Ties")
w, t, l = m.outcome_probs(0.5)
st.markdown(
    f"""
The expected score is split into win, tie and loss chances using a draw factor of {D}. Two evenly matched
teams have about a **{t:.0%}** chance of tying, and the chance falls as the gap grows. This only affects
the Win/Tie/Loss % shown on the site, not the ratings.
"""
)

st.markdown("### Teams over time")
st.markdown(
    """
* **Between seasons** every team is pulled {off:.0%} of the way toward the average of the division it's
  playing in next. Rosters change, and testing on past seasons showed this predicts the next season better
  than carrying ratings over unchanged.
* **Teams returning from a break** are pulled further: {h1:.0%} after one missed season, {h2:.0%} after two.
* **Renamed teams** keep their rating. Every name a team has used is tracked.
* **Merged teams** that split back up start from the merged team's rating.
* **New teams** start at their division's average rating.
* **Divisions** come from the latest league schedule.
""".format(off=_rules.hiatus_fraction(0), h1=_rules.hiatus_fraction(1), h2=_rules.hiatus_fraction(2))
)
