"""SodaPlotter: Plotly visualizations for SODA DataFrames."""
import logging
from typing import Any, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger("nyc_open_data.plotter")

_PALETTE = ["#0057A8", "#C8102E", "#00875A", "#FF6B00", "#7B2D8B"]

_FT_LAYOUT: dict[str, Any] = dict(
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
    margin=dict(l=60, r=60, t=80, b=60),
)


class SodaPlotter:
    """Visualization wrapper for SODA DataFrames.

    Args:
        df: DataFrame returned by SodaClient.fetch().
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
        x_col: str,
        y_col: str,
        x_label: str = "",
        y_label: str = "",
        color_col: Optional[str] = None,
    ) -> go.Figure:
        """Time-series line chart.

        Args:
            x_col: Column for x-axis (typically a date column).
            y_col: Column for y-axis (numeric).
            x_label: X-axis title.
            y_label: Y-axis title.
            color_col: Column to split into separate traces (optional).

        Returns:
            Plotly Figure.
        """
        fig = go.Figure()

        if color_col:
            groups = self.df[color_col].unique()
            for i, grp in enumerate(sorted(groups)):
                mask = self.df[color_col] == grp
                sub = self.df[mask]
                fig.add_trace(go.Scatter(
                    x=sub[x_col],
                    y=sub[y_col],
                    name=str(grp),
                    line=dict(color=_PALETTE[i % len(_PALETTE)], width=2),
                    hovertemplate=f"<b>{grp}</b>: %{{y}}<extra></extra>",
                ))
        else:
            fig.add_trace(go.Scatter(
                x=self.df[x_col],
                y=self.df[y_col],
                name=y_col,
                line=dict(color=_PALETTE[0], width=2),
                hovertemplate="%{y}<extra></extra>",
            ))

        layout = {**_FT_LAYOUT, "title": dict(text=self.title, font=dict(size=15)), "height": self.height}
        if x_label:
            layout["xaxis"]["title"] = x_label  # type: ignore[index]
        if y_label:
            layout["yaxis"]["title"] = y_label  # type: ignore[index]
        fig.update_layout(**layout)

        logger.debug("line() built: x=%s y=%s", x_col, y_col)
        return fig

    def bar(
        self,
        x_col: str,
        y_col: str,
        x_label: str = "",
        y_label: str = "",
        horizontal: bool = False,
        top_n: Optional[int] = None,
        color: str = _PALETTE[0],
    ) -> go.Figure:
        """Bar chart for categorical aggregations.

        Args:
            x_col: Column for categories (x-axis when vertical).
            y_col: Column for values (y-axis when vertical).
            x_label: X-axis title.
            y_label: Y-axis title.
            horizontal: If True, swap axes (better for many categories).
            top_n: Keep only the top N categories by value.
            color: Bar fill color.

        Returns:
            Plotly Figure.
        """
        df = self.df.copy()
        if top_n:
            df = df.nlargest(top_n, y_col)

        df = df.sort_values(y_col, ascending=horizontal)

        if horizontal:
            trace = go.Bar(
                x=df[y_col],
                y=df[x_col],
                orientation="h",
                marker_color=color,
                hovertemplate=f"<b>%{{y}}</b>: %{{x}}<extra></extra>",
            )
        else:
            trace = go.Bar(
                x=df[x_col],
                y=df[y_col],
                orientation="v",
                marker_color=color,
                hovertemplate=f"<b>%{{x}}</b>: %{{y}}<extra></extra>",
            )

        fig = go.Figure(trace)
        layout = {**_FT_LAYOUT, "title": dict(text=self.title, font=dict(size=15)), "height": self.height}
        layout["hovermode"] = "closest"
        if x_label:
            layout["xaxis"]["title"] = x_label  # type: ignore[index]
        if y_label:
            layout["yaxis"]["title"] = y_label  # type: ignore[index]
        fig.update_layout(**layout)

        logger.debug("bar() built: x=%s y=%s horizontal=%s top_n=%s", x_col, y_col, horizontal, top_n)
        return fig

    def choropleth(
        self,
        geojson: dict,
        locations_col: str,
        value_col: str,
        featureid_key: str = "properties.name",
        mapbox_style: str = "carto-positron",
        center: Optional[dict] = None,
        zoom: float = 9.5,
        color_scale: str = "Blues",
    ) -> go.Figure:
        """Choropleth map for geographic distribution.

        Args:
            geojson: GeoJSON FeatureCollection dict.
            locations_col: DataFrame column matching ``featureid_key`` values.
            value_col: Numeric column to shade by.
            featureid_key: GeoJSON property path used to join with ``locations_col``.
            mapbox_style: Mapbox base layer (no token needed for carto styles).
            center: Dict with ``lat`` and ``lon`` keys. Defaults to NYC center.
            zoom: Initial zoom level.
            color_scale: Plotly color scale name.

        Returns:
            Plotly Figure (Mapbox-based choropleth).
        """
        center = center or {"lat": 40.7128, "lon": -74.0060}

        fig = px.choropleth_mapbox(
            self.df,
            geojson=geojson,
            locations=locations_col,
            color=value_col,
            featureidkey=featureid_key,
            center=center,
            zoom=zoom,
            mapbox_style=mapbox_style,
            color_continuous_scale=color_scale,
            title=self.title,
            height=self.height,
        )
        fig.update_layout(
            font=_FT_LAYOUT["font"],
            paper_bgcolor="white",
            margin=dict(l=0, r=0, t=60, b=0),
        )

        logger.debug("choropleth() built: locations=%s value=%s", locations_col, value_col)
        return fig
