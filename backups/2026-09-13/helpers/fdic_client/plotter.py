import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PALETTE = ["#0057A8", "#C8102E", "#00875A", "#F5A623", "#7B68EE", "#FF6B6B"]
BG = "#0f1117"
GRID = "#1e2130"
TEXT = "#e0e0e0"


def _base_layout(title: str) -> dict:
    return dict(
        title=dict(text=title, font=dict(color=TEXT, size=16)),
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=TEXT, family="Inter, Arial, sans-serif"),
        xaxis=dict(gridcolor=GRID, showgrid=True, zeroline=False),
        yaxis=dict(gridcolor=GRID, showgrid=True, zeroline=False),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID),
        margin=dict(l=60, r=40, t=60, b=50),
        hovermode="x unified",
    )


class FDICPlotter:
    """Plotly chart helper for FDIC BankFind data."""

    def __init__(self, data: pd.DataFrame, title: str = "", height: int = 500):
        if isinstance(data, pd.Series):
            data = data.to_frame()
        self.data = data
        self.title = title
        self.height = height

    def line(
        self,
        value_fmt: str = "%{y:,.2f}",
        y_label: str = "",
        x_label: str = "",
    ) -> go.Figure:
        fig = go.Figure()
        for i, col in enumerate(self.data.columns):
            fig.add_trace(go.Scatter(
                x=self.data.index,
                y=self.data[col],
                name=str(col),
                mode="lines",
                line=dict(color=PALETTE[i % len(PALETTE)], width=2),
                hovertemplate=f"<b>{col}</b>: {value_fmt}<extra></extra>",
            ))
        layout = _base_layout(self.title)
        layout["xaxis"]["title"] = x_label
        layout["yaxis"]["title"] = y_label
        layout["height"] = self.height
        fig.update_layout(**layout)
        return fig

    def dual_axis(
        self,
        left_col: str,
        right_col: str,
        left_fmt: str = "%{y:,.2f}",
        right_fmt: str = "%{y:,.2f}",
        left_label: str = "",
        right_label: str = "",
    ) -> go.Figure:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(
            x=self.data.index, y=self.data[left_col],
            name=left_col, mode="lines",
            line=dict(color=PALETTE[0], width=2),
            hovertemplate=f"<b>{left_col}</b>: {left_fmt}<extra></extra>",
        ), secondary_y=False)
        fig.add_trace(go.Scatter(
            x=self.data.index, y=self.data[right_col],
            name=right_col, mode="lines",
            line=dict(color=PALETTE[1], width=2),
            hovertemplate=f"<b>{right_col}</b>: {right_fmt}<extra></extra>",
        ), secondary_y=True)
        layout = _base_layout(self.title)
        layout["height"] = self.height
        fig.update_layout(**layout)
        fig.update_yaxes(title_text=left_label, secondary_y=False,
                         gridcolor=GRID, zeroline=False)
        fig.update_yaxes(title_text=right_label, secondary_y=True,
                         gridcolor=GRID, zeroline=False, showgrid=False)
        return fig

    def bar(
        self,
        value_fmt: str = "%{y:,.2f}",
        y_label: str = "",
        x_label: str = "",
    ) -> go.Figure:
        """Bar chart — good for cross-section comparisons (one row per bank)."""
        fig = go.Figure()
        for i, col in enumerate(self.data.columns):
            fig.add_trace(go.Bar(
                x=self.data.index,
                y=self.data[col],
                name=str(col),
                marker_color=PALETTE[i % len(PALETTE)],
                hovertemplate=f"<b>{col}</b>: {value_fmt}<extra></extra>",
            ))
        layout = _base_layout(self.title)
        layout["xaxis"]["title"] = x_label
        layout["yaxis"]["title"] = y_label
        layout["height"] = self.height
        layout["barmode"] = "group"
        fig.update_layout(**layout)
        return fig

    def failures_timeline(self) -> go.Figure:
        """Bar chart of bank failure counts by year, with estimated cost overlay.

        Expects a DataFrame from FDICClient.get_failures() with FAILDATE and COST columns.
        """
        df = self.data.copy()
        if "FAILDATE" not in df.columns:
            raise ValueError("DataFrame must have a FAILDATE column")

        df["year"] = pd.to_datetime(df["FAILDATE"]).dt.year
        counts = df.groupby("year").size().rename("count")
        costs = df.groupby("year")["COST"].sum().rename("cost_bn") / 1000 if "COST" in df.columns else None

        fig = make_subplots(specs=[[{"secondary_y": bool(costs is not None)}]])
        fig.add_trace(go.Bar(
            x=counts.index, y=counts.values,
            name="# Failures",
            marker_color=PALETTE[1],
            hovertemplate="<b>%{x}</b><br>Failures: %{y}<extra></extra>",
        ), secondary_y=False)

        if costs is not None:
            fig.add_trace(go.Scatter(
                x=costs.index, y=costs.values,
                name="Est. Cost ($B)",
                mode="lines+markers",
                line=dict(color=PALETTE[2], width=2),
                hovertemplate="<b>%{x}</b><br>Cost: $%{y:,.1f}B<extra></extra>",
            ), secondary_y=True)

        layout = _base_layout(self.title or "FDIC Bank Failures by Year")
        layout["height"] = self.height
        fig.update_layout(**layout)
        fig.update_yaxes(title_text="Number of Failures", secondary_y=False,
                         gridcolor=GRID, zeroline=False)
        if costs is not None:
            fig.update_yaxes(title_text="Estimated Cost ($B)", secondary_y=True,
                             gridcolor=GRID, zeroline=False, showgrid=False)
        return fig
