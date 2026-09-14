import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from espn_soccer_client import ESPNSoccerClient, aggregate_player_stats, aggregate_team_stats, SoccerPer90Plotter, SoccerTeamPlotter

client = ESPNSoccerClient(league='fifa.world')
event_ids = client.completed_match_ids('20260601-20260701')
print(f"{len(event_ids)} completed matches")

repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
out_dir = os.path.join(repo_root, "reports", "fifa-wc-2026")

FOOTNOTE_CSS = """
<style>
  body { margin: 0; padding: 0 1rem; }
  .plot-wrap { width: 100%; max-width: 1100px; margin: 0 auto; }
  .plot-wrap > div { width: 100% !important; }
  .chart-footnote { font-family: system-ui, sans-serif; font-size: 0.8rem; color: #555;
    max-width: 1100px; margin: 0.5rem auto 2rem; padding: 0.75rem 1rem;
    border-top: 1px solid #e5e5e5; }
  .chart-footnote dt { font-weight: 600; display: inline; }
  .chart-footnote dd { display: inline; margin: 0 0 0 0.3rem; }
  .chart-footnote li { margin-bottom: 0.3rem; }
  .chart-footnote ul { list-style: none; padding-left: 0; }
  @media (max-width: 600px) {
    body { padding: 0 0.5rem; }
    .chart-footnote { font-size: 0.95rem; line-height: 1.5; padding: 0.75rem 0.25rem; }
  }
</style>
"""

MOBILE_RESIZE_JS = """
<script>
(function(){
  function isMobile(){ return window.innerWidth <= 600; }
  function applyLayout(gd){
    if(!gd) return;
    var update = isMobile() ? {
      'font.size': 10,
      'title.font.size': 14,
      'legend.orientation': 'h',
      'legend.x': 0, 'legend.xanchor': 'left',
      'legend.y': -0.25, 'legend.yanchor': 'top',
      'xaxis.title.font.size': 11,
      'yaxis.title.font.size': 11,
      'margin': {l: 45, r: 10, t: 40, b: 90},
      'height': 480
    } : {
      'font.size': 12,
      'title.font.size': 17,
      'legend.orientation': 'v',
      'legend.x': 0.01, 'legend.xanchor': 'left',
      'legend.y': 0.99, 'legend.yanchor': 'top',
      'xaxis.title.font.size': 13,
      'yaxis.title.font.size': 13,
      'margin': {l: 60, r: 20, t: 60, b: 60},
      'height': 650
    };
    Plotly.relayout(gd, update);
  }
  window.addEventListener('load', function(){
    var gd = document.querySelector('.plot-wrap .plotly-graph-div');
    applyLayout(gd);
    var resizeTimer;
    window.addEventListener('resize', function(){
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function(){ applyLayout(gd); }, 200);
    });
  });
})();
</script>
"""

def write_with_footnote(fig, path, terms):
    body = fig.to_html(full_html=False, include_plotlyjs="cdn", config={"responsive": True})
    items = "".join(f"<li><dt>{term}</dt><dd>— {definition}</dd></li>" for term, definition in terms)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WC 2026 Chart</title>{FOOTNOTE_CSS}</head>
<body>
<div class="plot-wrap">{body}</div>
{MOBILE_RESIZE_JS}
<dl class="chart-footnote"><ul>{items}</ul></dl>
</body>
</html>"""
    with open(path, "w") as f:
        f.write(html)


players = aggregate_player_stats(
    client, event_ids,
    stat_names=("totalGoals", "totalShots", "shotsOnTarget"),
)
plotter = SoccerPer90Plotter(players, min_minutes=1)
fig = plotter.goals_vs_shots_scatter(min_goals=1, title="FIFA World Cup 2026 — Goals/90 vs Shots/90")
write_with_footnote(fig, f"{out_dir}/goals_shots.html", [
    ("Goals/90", "goals scored, normalized to a 90-minute match (total goals ÷ minutes played × 90)."),
    ("Shots/90", "shots taken, normalized to a 90-minute match."),
    ("Bubble size", "minutes played in the tournament so far — bigger bubble, more minutes."),
    ("Dotted lines", "median Goals/90 and median Shots/90 across all qualifying players, splitting the chart into four quadrants."),
    ("Min. 1 goal filter", "only players who have scored at least once are shown."),
    ("Color", "confederation of the player's national team."),
])
print("player chart done")

teams = aggregate_team_stats(client, event_ids)
tp = SoccerTeamPlotter(teams)

RANK_NOTE = ("Bubble size", "bigger for a better (lower-numbered) FIFA Men's World Ranking position — size scales "
             "inversely with the log of the rank, so the spread is gentle rather than dramatic.")
MEDIAN_NOTE = ("Dotted lines", "median value on each axis across all teams shown, splitting the chart into four quadrants.")
COLOR_NOTE = ("Color", "confederation (continental governing body) of the team.")
MATCH_NOTE = ("/match rate", "stat total divided by matches played, so teams with different match counts compare fairly.")

fig = tp.possession_vs_shots_scatter(title="FIFA World Cup 2026 — Possession% vs Shots/match")
write_with_footnote(fig, f"{out_dir}/possession_shots.html", [
    ("Possession%", "average share of match time the team controlled the ball."),
    ("Shots/match", "average shots taken per match."),
    RANK_NOTE, MEDIAN_NOTE, MATCH_NOTE, COLOR_NOTE,
])

fig = tp.shot_conversion_vs_shots_scatter(title="FIFA World Cup 2026 — Shot Conversion% vs Shots/match")
write_with_footnote(fig, f"{out_dir}/conversion_shots.html", [
    ("Shot Conversion%", "percentage of a team's shots that result in a goal."),
    ("Shots/match", "average shots taken per match."),
    RANK_NOTE, MEDIAN_NOTE, MATCH_NOTE, COLOR_NOTE,
])

fig = tp.longball_vs_pass_scatter(title="FIFA World Cup 2026 — Long Ball% vs Pass%")
write_with_footnote(fig, f"{out_dir}/longball_pass.html", [
    ("Long Ball%", "share of a team's passes classified as long balls (longer, more direct passes)."),
    ("Pass%", "pass completion accuracy — completed passes ÷ attempted passes."),
    RANK_NOTE, MEDIAN_NOTE, COLOR_NOTE,
])

fig = tp.crosses_accuracy_scatter(title="FIFA World Cup 2026 — Accurate Crosses vs Total Crosses/match")
write_with_footnote(fig, f"{out_dir}/crosses.html", [
    ("Total Crosses/match", "average crosses attempted per match."),
    ("Accurate Crosses/match", "average crosses per match that successfully found a teammate."),
    RANK_NOTE, MEDIAN_NOTE, COLOR_NOTE,
])

print("team charts done")
