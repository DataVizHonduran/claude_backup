import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from typing import Optional

CITY_COLORS = {
    "nyc": "#0057A8",
    "chicago": "#C8102E",
    "la": "#00875A",
    "houston": "#F5A623",
    "miami": "#9B59B6",
    "boston": "#E67E22",
    "dallas": "#1ABC9C",
    "default": "#7F8C8D",
}

TEMPLATE = "plotly_white"


class WeatherPlotter:
    """Plotly chart builder for NOAA/EPA weather and air quality data."""

    def __init__(self, df: pd.DataFrame, title: str):
        self.df = df.copy()
        self.title = title

    def line(
        self,
        col: str,
        y_label: str = "",
        value_fmt: str = "%{y:.1f}",
        color: str = "#0057A8",
        date_col: str = "date",
    ) -> go.Figure:
        """Single time series line chart."""
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=self.df[date_col],
            y=self.df[col],
            mode="lines",
            name=col,
            line=dict(color=color, width=1.8),
            hovertemplate=f"{value_fmt}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text=self.title, font=dict(size=16)),
            xaxis_title="Date",
            yaxis_title=y_label,
            template=TEMPLATE,
            hovermode="x unified",
        )
        return fig

    def multi_city(
        self,
        city_cols: dict,
        y_label: str = "",
        value_fmt: str = "%{y:.1f}",
        date_col: str = "date",
    ) -> go.Figure:
        """Overlay multiple city series.

        Args:
            city_cols: {'NYC': 'nyc_col', 'Chicago': 'chi_col', ...}
                       Keys are display labels, values are DataFrame column names.
                       Optionally pass tuples: {'NYC': ('nyc_col', '#custom_color')}
        """
        fig = go.Figure()
        for i, (label, col_spec) in enumerate(city_cols.items()):
            if isinstance(col_spec, tuple):
                col, color = col_spec
            else:
                col = col_spec
                key = label.lower().replace(" ", "")
                color = CITY_COLORS.get(key, list(CITY_COLORS.values())[i % len(CITY_COLORS)])

            if col not in self.df.columns:
                continue
            fig.add_trace(go.Scatter(
                x=self.df[date_col],
                y=self.df[col],
                mode="lines",
                name=label,
                line=dict(color=color, width=1.8),
                hovertemplate=f"{label}: {value_fmt}<extra></extra>",
            ))

        fig.update_layout(
            title=dict(text=self.title, font=dict(size=16)),
            xaxis_title="Date",
            yaxis_title=y_label,
            template=TEMPLATE,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        return fig

    def heatmap(
        self,
        value_col: str,
        date_col: str = "date",
        color_scale: str = "RdYlBu_r",
        z_label: str = "",
    ) -> go.Figure:
        """Year × month heatmap grid.

        Works best with monthly or daily-aggregated-to-monthly data.
        """
        df = self.df.copy()
        df["year"] = pd.to_datetime(df[date_col]).dt.year
        df["month"] = pd.to_datetime(df[date_col]).dt.month

        pivot = df.pivot_table(index="year", columns="month", values=value_col, aggfunc="mean")
        pivot = pivot.sort_index(ascending=False)

        month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        col_labels = [month_labels[m - 1] for m in pivot.columns]

        fig = go.Figure(go.Heatmap(
            z=pivot.values,
            x=col_labels,
            y=[str(y) for y in pivot.index],
            colorscale=color_scale,
            colorbar=dict(title=z_label),
            hovertemplate="Year: %{y}<br>Month: %{x}<br>Value: %{z:.2f}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text=self.title, font=dict(size=16)),
            template=TEMPLATE,
            yaxis=dict(title="Year"),
            xaxis=dict(title="Month"),
        )
        return fig

    def bar(
        self,
        col: str,
        y_label: str = "",
        value_fmt: str = "%{y:.1f}",
        color: str = "#0057A8",
        date_col: str = "date",
    ) -> go.Figure:
        """Bar chart — useful for precipitation or event counts."""
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=self.df[date_col],
            y=self.df[col],
            name=col,
            marker_color=color,
            hovertemplate=f"{value_fmt}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text=self.title, font=dict(size=16)),
            xaxis_title="Date",
            yaxis_title=y_label,
            template=TEMPLATE,
        )
        return fig

    def dual_axis(
        self,
        left_col: str,
        right_col: str,
        left_label: str = "",
        right_label: str = "",
        left_fmt: str = "%{y:.1f}",
        right_fmt: str = "%{y:.1f}",
        left_color: str = "#0057A8",
        right_color: str = "#C8102E",
        date_col: str = "date",
    ) -> go.Figure:
        """Two series on separate y-axes."""
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(
            x=self.df[date_col], y=self.df[left_col],
            name=left_col, line=dict(color=left_color, width=1.8),
            hovertemplate=f"{left_fmt}<extra></extra>",
        ), secondary_y=False)
        fig.add_trace(go.Scatter(
            x=self.df[date_col], y=self.df[right_col],
            name=right_col, line=dict(color=right_color, width=1.8),
            hovertemplate=f"{right_fmt}<extra></extra>",
        ), secondary_y=True)
        fig.update_layout(
            title=dict(text=self.title, font=dict(size=16)),
            template=TEMPLATE,
            hovermode="x unified",
        )
        fig.update_yaxes(title_text=left_label, secondary_y=False)
        fig.update_yaxes(title_text=right_label, secondary_y=True)
        return fig
