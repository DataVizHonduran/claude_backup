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


class BEAPlotter:
    """Plotly chart helper for BEA time-series data."""

    def __init__(self, data: pd.DataFrame, title: str = ""):
        """
        data: DatetimeIndex DataFrame, one column per series.
              Or a single pd.Series (converted automatically).
        title: chart title string.
        """
        if isinstance(data, pd.Series):
            data = data.to_frame()
        self.data = data
        self.title = title

    def line(
        self,
        value_fmt: str = "%{y:,.1f}",
        y_label: str = "",
        x_label: str = "",
    ) -> go.Figure:
        fig = go.Figure()
        for i, col in enumerate(self.data.columns):
            fig.add_trace(go.Scatter(
                x=self.data.index,
                y=self.data[col],
                name=col,
                mode="lines",
                line=dict(color=PALETTE[i % len(PALETTE)], width=2),
                hovertemplate=f"<b>{col}</b>: {value_fmt}<extra></extra>",
            ))
        layout = _base_layout(self.title)
        layout["xaxis"]["title"] = x_label
        layout["yaxis"]["title"] = y_label
        fig.update_layout(**layout)
        return fig

    def dual_axis(
        self,
        left_col: str,
        right_col: str,
        left_fmt: str = "%{y:,.1f}",
        right_fmt: str = "%{y:,.1f}",
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
        fig.update_layout(**layout)
        fig.update_yaxes(title_text=left_label, secondary_y=False,
                         gridcolor=GRID, zeroline=False)
        fig.update_yaxes(title_text=right_label, secondary_y=True,
                         gridcolor=GRID, zeroline=False, showgrid=False)
        return fig

    def bar(
        self,
        value_fmt: str = "%{y:,.1f}",
        y_label: str = "",
    ) -> go.Figure:
        fig = go.Figure()
        for i, col in enumerate(self.data.columns):
            fig.add_trace(go.Bar(
                x=self.data.index,
                y=self.data[col],
                name=col,
                marker_color=PALETTE[i % len(PALETTE)],
                hovertemplate=f"<b>{col}</b>: {value_fmt}<extra></extra>",
            ))
        layout = _base_layout(self.title)
        layout["yaxis"]["title"] = y_label
        fig.update_layout(**layout, barmode="group")
        return fig

    def with_trend(
        self,
        window: int = 4,
        value_fmt: str = "%{y:,.1f}",
        y_label: str = "",
    ) -> go.Figure:
        fig = go.Figure()
        col = self.data.columns[0]
        fig.add_trace(go.Scatter(
            x=self.data.index, y=self.data[col],
            name=col, mode="lines",
            line=dict(color=PALETTE[0], width=1.5, dash="dot"),
            hovertemplate=f"<b>{col}</b>: {value_fmt}<extra></extra>",
        ))
        trend = self.data[col].rolling(window).mean()
        fig.add_trace(go.Scatter(
            x=self.data.index, y=trend,
            name=f"{window}-period MA",
            mode="lines",
            line=dict(color=PALETTE[1], width=2.5),
            hovertemplate=f"<b>MA</b>: {value_fmt}<extra></extra>",
        ))
        layout = _base_layout(self.title)
        layout["yaxis"]["title"] = y_label
        fig.update_layout(**layout)
        return fig
