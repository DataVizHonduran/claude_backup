"""FredPlotter: Financial-grade visualization for FRED DataFrames."""
import logging
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger("fred_client.plotter")

# NBER recession date ranges — update as needed
NBER_RECESSIONS = [
    ("1937-05-01", "1938-06-01"),
    ("1945-02-01", "1945-10-01"),
    ("1948-11-01", "1949-10-01"),
    ("1953-07-01", "1954-05-01"),
    ("1957-08-01", "1958-04-01"),
    ("1960-04-01", "1961-02-01"),
    ("1969-12-01", "1970-11-01"),
    ("1973-11-01", "1975-03-01"),
    ("1980-01-01", "1980-07-01"),
    ("1981-07-01", "1982-11-01"),
    ("1990-07-01", "1991-03-01"),
    ("2001-03-01", "2001-11-01"),
    ("2007-12-01", "2009-06-01"),
    ("2020-02-01", "2020-04-01"),
]

# Palette: assign consistent colors per entity
ENTITY_COLORS = {
    "us":  "#0057A8",
    "cn":  "#C8102E",
    "em":  "#00875A",
    "eu":  "#FF6B00",
    "default": ["#0057A8", "#C8102E", "#00875A", "#FF6B00", "#7B2D8B"],
}

_FT_LAYOUT = dict(
    font=dict(family="Helvetica Neue, Arial, sans-serif", size=12, color="#333333"),
    paper_bgcolor="white",
    plot_bgcolor="white",
    xaxis=dict(
        showgrid=False,
        zeroline=False,
        showline=True,
        linecolor="#CCCCCC",
        tickfont=dict(size=11),
    ),
    yaxis=dict(
        showgrid=True,
        gridcolor="#E5E5E5",
        gridwidth=1,
        zeroline=False,
        showline=False,
        tickfont=dict(size=11),
    ),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
        bgcolor="rgba(0,0,0,0)",
        bordercolor="rgba(0,0,0,0)",
    ),
    hovermode="x unified",
    margin=dict(l=60, r=60, t=60, b=60),
)


class FredPlotter:
    """Visualization wrapper for FRED DataFrames.

    Args:
        df: DataFrame with DatetimeIndex. Each column is a series to plot.
        title: Chart title.
        height: Figure height in pixels.
    """

    def __init__(self, df: pd.DataFrame, title: str = "", height: int = 500) -> None:
        self.df = df
        self.title = title
        self.height = height

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def line(
        self,
        value_fmt: str = "%{y:.2f}",
        y_label: str = "",
        colors: Optional[list[str]] = None,
        recession_shading: bool = True,
    ) -> go.Figure:
        """Single-axis line chart for one or more series.

        Args:
            value_fmt: Plotly hovertemplate format string for y values.
            y_label: Y-axis title.
            colors: Override trace colors. Falls back to ENTITY_COLORS defaults.
            recession_shading: Shade NBER recession periods.

        Returns:
            Plotly Figure.
        """
        fig = go.Figure()
        palette = colors or ENTITY_COLORS["default"]

        for i, col in enumerate(self.df.columns):
            color = palette[i % len(palette)]
            fig.add_trace(go.Scatter(
                x=self.df.index,
                y=self.df[col],
                name=col,
                line=dict(color=color, width=2),
                hovertemplate=f"<b>{col}</b>: {value_fmt}<extra></extra>",
            ))

        layout = {**_FT_LAYOUT, "title": dict(text=self.title, font=dict(size=15)), "height": self.height}
        if y_label:
            layout["yaxis"]["title"] = y_label
        fig.update_layout(**layout)

        if recession_shading:
            _add_recession_shading(fig, x_min=self.df.index.min(), x_max=self.df.index.max())

        logger.debug("line() chart built: %d series", len(self.df.columns))
        return fig

    def dual_axis(
        self,
        left_col: str,
        right_col: str,
        left_fmt: str = "%{y:.2f}",
        right_fmt: str = "%{y:.0f}",
        left_label: str = "",
        right_label: str = "",
        left_color: str = "#0057A8",
        right_color: str = "#C8102E",
        recession_shading: bool = True,
    ) -> go.Figure:
        """Dual-axis chart: left series vs right series on independent scales.

        Args:
            left_col: Column name plotted on the left y-axis.
            right_col: Column name plotted on the right y-axis.
            left_fmt: Hovertemplate format for left series.
            right_fmt: Hovertemplate format for right series.
            left_label: Left y-axis title.
            right_label: Right y-axis title.
            left_color: Line color for left series.
            right_color: Line color for right series.
            recession_shading: Shade NBER recession periods.

        Returns:
            Plotly Figure with two y-axes.
        """
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        fig.add_trace(go.Scatter(
            x=self.df.index,
            y=self.df[left_col],
            name=left_col,
            line=dict(color=left_color, width=2),
            hovertemplate=f"<b>{left_col}</b>: {left_fmt}<extra></extra>",
        ), secondary_y=False)

        fig.add_trace(go.Scatter(
            x=self.df.index,
            y=self.df[right_col],
            name=right_col,
            line=dict(color=right_color, width=2, dash="dot"),
            hovertemplate=f"<b>{right_col}</b>: {right_fmt}<extra></extra>",
        ), secondary_y=True)

        layout = {**_FT_LAYOUT, "title": dict(text=self.title, font=dict(size=15)), "height": self.height}
        fig.update_layout(**layout)
        fig.update_yaxes(title_text=left_label, secondary_y=False, showgrid=True, gridcolor="#E5E5E5")
        fig.update_yaxes(title_text=right_label, secondary_y=True, showgrid=False)

        if recession_shading:
            _add_recession_shading(fig, x_min=self.df.index.min(), x_max=self.df.index.max())

        logger.debug("dual_axis() chart built: %s / %s", left_col, right_col)
        return fig

    def with_trend(
        self,
        window: int = 12,
        value_fmt: str = "%{y:.2f}",
        y_label: str = "",
        recession_shading: bool = True,
    ) -> go.Figure:
        """Line chart with an N-period rolling mean overlay per series.

        Args:
            window: Rolling window size in periods (default 12).
            value_fmt: Hovertemplate format for y values.
            y_label: Y-axis title.
            recession_shading: Shade NBER recession periods.

        Returns:
            Plotly Figure with raw series + rolling mean traces.
        """
        fig = go.Figure()
        palette = ENTITY_COLORS["default"]

        for i, col in enumerate(self.df.columns):
            color = palette[i % len(palette)]
            rolling = self.df[col].rolling(window=window, min_periods=1).mean()

            fig.add_trace(go.Scatter(
                x=self.df.index,
                y=self.df[col],
                name=col,
                line=dict(color=color, width=1.5, dash="dot"),
                opacity=0.5,
                hovertemplate=f"<b>{col}</b>: {value_fmt}<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=self.df.index,
                y=rolling,
                name=f"{col} ({window}m avg)",
                line=dict(color=color, width=2.5),
                hovertemplate=f"<b>{col} {window}m</b>: {value_fmt}<extra></extra>",
            ))

        layout = {**_FT_LAYOUT, "title": dict(text=self.title, font=dict(size=15)), "height": self.height}
        if y_label:
            layout["yaxis"]["title"] = y_label
        fig.update_layout(**layout)

        if recession_shading:
            _add_recession_shading(fig, x_min=self.df.index.min(), x_max=self.df.index.max())

        logger.debug("with_trend() chart built: window=%d, %d series", window, len(self.df.columns))
        return fig


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _add_recession_shading(fig: go.Figure, x_min=None, x_max=None) -> None:
    """Add grey NBER recession vrects clipped to [x_min, x_max]."""
    for start, end in NBER_RECESSIONS:
        s = pd.Timestamp(start)
        e = pd.Timestamp(end)
        if x_min is not None and e < x_min:
            continue
        if x_max is not None and s > x_max:
            continue
        fig.add_vrect(
            x0=max(s, x_min) if x_min is not None else s,
            x1=min(e, x_max) if x_max is not None else e,
            fillcolor="#CCCCCC",
            opacity=0.25,
            layer="below",
            line_width=0,
        )
