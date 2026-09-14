"""Plotly scatter charts for per-90 soccer player stats."""
import math
import statistics

import plotly.graph_objects as go

from .client import CONFEDERATION_COLORS


def _rank_size(rank):
    """Bigger bubble for a better (lower-numbered) FIFA ranking."""
    return max(26 - 4.5 * math.log(rank), 6)


def _add_median_quadrants(fig, x_vals, y_vals):
    """Dotted lines at the median of each axis, splitting the chart into quadrants."""
    fig.add_vline(x=statistics.median(x_vals), line_dash="dot", line_color="gray", line_width=1)
    fig.add_hline(y=statistics.median(y_vals), line_dash="dot", line_color="gray", line_width=1)


class SoccerPer90Plotter:
    def __init__(self, players, min_minutes=1):
        """players: dict from aggregate_player_stats (athlete id -> record)."""
        self.players = [p for p in players.values() if p["minutes"] >= min_minutes]

    def per90_scatter(self, x_stat, y_stat, size_stat="minutes",
                       title="Per-90 Scatter", x_label=None, y_label=None):
        """One trace per confederation so markers are categorically colored
        and a legend is shown (no continuous color scale)."""
        fig = go.Figure()

        all_x = [p[x_stat] / p["minutes"] * 90 for p in self.players]
        all_y = [p[y_stat] / p["minutes"] * 90 for p in self.players]

        confeds = sorted({p["confederation"] for p in self.players})
        for confed in confeds:
            group = [p for p in self.players if p["confederation"] == confed]
            names = [p["name"] for p in group]
            teams = [p["team"] for p in group]
            minutes = [p["minutes"] for p in group]
            x = [p[x_stat] / p["minutes"] * 90 for p in group]
            y = [p[y_stat] / p["minutes"] * 90 for p in group]
            sizes = [p[size_stat] / 3 for p in group]

            fig.add_trace(go.Scatter(
                x=x, y=y,
                mode="markers+text",
                name=confed,
                text=names,
                textposition="top center",
                textfont=dict(size=8),
                marker=dict(
                    size=sizes,
                    sizemode="area",
                    sizemin=4,
                    color=CONFEDERATION_COLORS.get(confed, CONFEDERATION_COLORS["Unknown"]),
                    line=dict(width=1, color="white"),
                ),
                customdata=list(zip(teams, minutes)),
                hovertemplate=(
                    "<b>%{text}</b><br>Team: %{customdata[0]}<br>"
                    f"Confederation: {confed}<br>"
                    "Minutes: %{customdata[1]}<br>"
                    f"{x_label or x_stat}: " + "%{x:.2f}<br>"
                    f"{y_label or y_stat}: " + "%{y:.2f}<extra></extra>"
                ),
            ))

        _add_median_quadrants(fig, all_x, all_y)

        fig.update_layout(
            title=title,
            xaxis_title=x_label or f"{x_stat}/90",
            yaxis_title=y_label or f"{y_stat}/90",
            template="plotly_white",
            legend=dict(title="Confederation", x=0.01, y=0.99,
                        xanchor="left", yanchor="top"),
            autosize=True,
            height=650,
        )
        return fig

    def goals_vs_shots_scatter(self, min_goals=1, title="Goals/90 vs Shots/90"):
        self.players = [p for p in self.players if p.get("totalGoals", 0) >= min_goals]
        return self.per90_scatter(
            x_stat="totalShots", y_stat="totalGoals",
            title=title, x_label="Shots/90", y_label="Goals/90",
        )


def _outlier_labels(rows, x, y, label_key, z_threshold=1.4):
    """Combined z-distance on both axes; outliers get their name, others get ''."""
    xs, ys = [r[x] for r in rows], [r[y] for r in rows]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx, sy = statistics.pstdev(xs) or 1, statistics.pstdev(ys) or 1
    labels = []
    for r in rows:
        zx, zy = (r[x] - mx) / sx, (r[y] - my) / sy
        labels.append(r[label_key] if (zx * zx + zy * zy) ** 0.5 > z_threshold else "")
    return labels


class SoccerTeamPlotter:
    def __init__(self, teams):
        """teams: dict from aggregate_team_stats (team name -> record)."""
        self.teams = [{"team": name, **rec} for name, rec in teams.items()]

    def team_scatter(self, x_stat, y_stat, title, x_label=None, y_label=None,
                      label_outliers_only=True):
        rows = self.teams
        labels = (_outlier_labels(rows, x_stat, y_stat, "team")
                  if label_outliers_only else [r["team"] for r in rows])
        fig = go.Figure()
        confeds = sorted({r["confederation"] for r in rows})
        for confed in confeds:
            idx = [i for i, r in enumerate(rows) if r["confederation"] == confed]
            group = [rows[i] for i in idx]
            fig.add_trace(go.Scatter(
                x=[r[x_stat] for r in group], y=[r[y_stat] for r in group],
                mode="markers+text",
                name=confed,
                text=[labels[i] for i in idx],
                textposition="top center",
                textfont=dict(size=9),
                marker=dict(
                    size=[_rank_size(r["rank"]) for r in group],
                    sizemin=4,
                    color=CONFEDERATION_COLORS.get(confed, CONFEDERATION_COLORS["Unknown"]),
                    line=dict(width=1, color="white"),
                ),
                customdata=[(r["team"], r["matches"], r["rank"]) for r in group],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    f"Confederation: {confed}<br>Matches: " + "%{customdata[1]}<br>"
                    "FIFA Rank: %{customdata[2]}<br>"
                    f"{x_label or x_stat}: " + "%{x:.2f}<br>"
                    f"{y_label or y_stat}: " + "%{y:.2f}<extra></extra>"
                ),
            ))

        _add_median_quadrants(fig, [r[x_stat] for r in rows], [r[y_stat] for r in rows])

        fig.update_layout(
            title=title,
            xaxis_title=x_label or x_stat, yaxis_title=y_label or y_stat,
            template="plotly_white",
            legend=dict(title="Confederation", x=0.01, y=0.99, xanchor="left", yanchor="top"),
            autosize=True, height=650,
        )
        return fig

    def possession_vs_shots_scatter(self, title="Possession% vs Shots/match"):
        return self.team_scatter("totalShots", "possessionPct", title,
                                  x_label="Shots/match", y_label="Possession%")

    def shot_conversion_vs_shots_scatter(self, title="Shot Conversion% vs Shots/match"):
        return self.team_scatter("totalShots", "shotPct", title,
                                  x_label="Shots/match", y_label="Shot Conversion%")

    def longball_vs_pass_scatter(self, title="Long Ball% vs Pass%"):
        return self.team_scatter("passPct", "longballPct", title,
                                  x_label="Pass%", y_label="Long Ball%")

    def crosses_accuracy_scatter(self, title="Accurate Crosses vs Total Crosses/match"):
        return self.team_scatter("totalCrosses", "accurateCrosses", title,
                                  x_label="Total Crosses/match", y_label="Accurate Crosses/match")
