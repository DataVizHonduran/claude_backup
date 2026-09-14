import sys, statistics
sys.path.insert(0, "/Users/macproajb/claude_projects")
from espn_soccer_client import ESPNSoccerClient, aggregate_player_stats
from espn_soccer_client.client import CONFEDERATION, CONFEDERATION_COLORS


def _team_stat(stats, name):
    for s in stats:
        if s["name"] == name:
            return float(s.get("displayValue", 0) or 0)
    return 0.0
import plotly.express as px
from datetime import date

client = ESPNSoccerClient(league="fifa.world")
event_ids = client.completed_match_ids("20260611-20260619")

TEAM_FIELDS = ["totalShots", "possessionPct", "passPct", "shotPct",
               "totalTackles", "interceptions", "longballPct",
               "foulsCommitted", "effectiveTackles", "accurateCrosses", "totalCrosses",
               "yellowCards"]
PCT_FIELDS = {"possessionPct", "passPct", "shotPct", "longballPct"}

teams = {}
for eid in event_ids:
    s = client.match_summary(eid)
    for t in s.get("boxscore", {}).get("teams", []):
        name = t["team"]["displayName"]
        rec = teams.setdefault(name, {"matches": 0, **{f: 0.0 for f in TEAM_FIELDS}})
        rec["matches"] += 1
        for f in TEAM_FIELDS:
            rec[f] += _team_stat(t.get("statistics", []), f)

team_rows = []
for name, rec in teams.items():
    m = rec["matches"]
    row = {"team": name, "confederation": CONFEDERATION.get(name, "Unknown"), "matches": m}
    for f in TEAM_FIELDS:
        row[f] = rec[f] / m
    team_rows.append(row)

PLAYER_FIELDS = ("totalGoals", "totalShots", "goalAssists", "foulsCommitted",
                  "foulsSuffered")
players = aggregate_player_stats(client, event_ids, stat_names=PLAYER_FIELDS)
player_rows = []
for pid, rec in players.items():
    if rec["minutes"] <= 0:
        continue
    row = {"name": rec["name"], "team": rec["team"],
           "confederation": rec["confederation"], "minutes": rec["minutes"]}
    for f in PLAYER_FIELDS:
        row[f] = rec[f] / rec["minutes"] * 90.0
        row[f + "_raw"] = rec[f]
    player_rows.append(row)


def outlier_label(rows, x, y, label_key):
    xs = [r[x] for r in rows]
    ys = [r[y] for r in rows]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx, sy = statistics.pstdev(xs) or 1, statistics.pstdev(ys) or 1
    for r in rows:
        zx = (r[x] - mx) / sx
        zy = (r[y] - my) / sy
        r["_label"] = r[label_key] if (zx * zx + zy * zy) ** 0.5 > 1.4 else ""
    return rows


def make_fig(rows, x, y, label_key, title, size_key=None):
    rows = outlier_label(rows, x, y, label_key)
    fig = px.scatter(
        rows, x=x, y=y, color="confederation", text="_label",
        size=size_key, hover_name=label_key,
        color_discrete_map=CONFEDERATION_COLORS, title=title,
    )
    fig.update_traces(textposition="top center", textfont_size=10)
    fig.update_layout(height=550)
    return fig


combos = [
    (team_rows, "totalShots", "possessionPct", "team", "Possession% vs Shots/match", "matches"),
    (team_rows, "possessionPct", "passPct", "team", "Pass% vs Possession%", "matches"),
    (team_rows, "totalShots", "shotPct", "team", "Shot Conversion% vs Shots/match", "matches"),
    (team_rows, "interceptions", "totalTackles", "team", "Tackles/match vs Interceptions/match", "matches"),
    (team_rows, "passPct", "longballPct", "team", "Long Ball% vs Pass%", "matches"),
    (team_rows, "effectiveTackles", "foulsCommitted", "team", "Fouls/match vs Effective Tackles/match", "matches"),
    (team_rows, "totalCrosses", "accurateCrosses", "team", "Accurate Crosses/match vs Total Crosses/match", "matches"),
    (player_rows, "totalShots", "totalGoals", "name", "Goals/90 vs Shots/90", "minutes"),
    (player_rows, "totalGoals", "goalAssists", "name", "Assists/90 vs Goals/90", "minutes"),
    (player_rows, "foulsSuffered", "foulsCommitted", "name", "Fouls Committed/90 vs Fouls Suffered/90", "minutes"),
    (team_rows, "foulsCommitted", "yellowCards", "team", "Yellow Cards/match vs Fouls Committed/match", "matches"),
]

parts = []
for rows, x, y, label_key, title, size_key in combos:
    fig = make_fig(rows, x, y, label_key, title, size_key)
    parts.append(f"<h2>{title}</h2>" + fig.to_html(full_html=False, include_plotlyjs=False))

out = f"/Users/macproajb/claude_projects/wc26_{date.today()}_combo_scatters.html"
html = (
    '<html><head><script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script></head><body>'
    + "".join(parts) + "</body></html>"
)
with open(out, "w") as f:
    f.write(html)
print(out)
print("teams:", len(team_rows), "players:", len(player_rows))
