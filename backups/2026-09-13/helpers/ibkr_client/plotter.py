import plotly.graph_objects as go
import pandas as pd

_BLUE = "#0057A8"
_RED = "#C8102E"
_GREEN = "#00875A"
_BG = "#F8F9FA"

_LAYOUT = dict(
    template="plotly_white",
    paper_bgcolor=_BG,
    plot_bgcolor=_BG,
    font=dict(family="Inter, Arial, sans-serif", size=12),
    margin=dict(l=60, r=20, t=60, b=50),
    hovermode="x unified",
)


class IBKRPlotter:
    def __init__(self, title: str = ""):
        self.title = title

    def candlestick(self, df: pd.DataFrame, title: str = None) -> go.Figure:
        fig = go.Figure(
            go.Candlestick(
                x=df.index,
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                increasing_line_color=_GREEN,
                decreasing_line_color=_RED,
                name="Price",
            )
        )
        if "volume" in df.columns:
            fig.add_bar(
                x=df.index,
                y=df["volume"],
                name="Volume",
                marker_color=_BLUE,
                opacity=0.3,
                yaxis="y2",
            )
            fig.update_layout(
                yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Volume"),
            )
        fig.update_layout(**_LAYOUT, title=title or self.title, xaxis_rangeslider_visible=False)
        return fig

    def line(self, df: pd.DataFrame, col: str, title: str = None, y_label: str = "") -> go.Figure:
        fig = go.Figure(
            go.Scatter(x=df.index, y=df[col], mode="lines", line=dict(color=_BLUE, width=2), name=col)
        )
        fig.update_layout(**_LAYOUT, title=title or self.title, yaxis_title=y_label)
        return fig

    def options_chain(
        self,
        strikes: list,
        call_ivs: list = None,
        put_ivs: list = None,
        title: str = None,
    ) -> go.Figure:
        fig = go.Figure()
        if call_ivs:
            fig.add_bar(x=strikes, y=call_ivs, name="Calls", marker_color=_GREEN, opacity=0.7)
        if put_ivs:
            fig.add_bar(x=strikes, y=put_ivs, name="Puts", marker_color=_RED, opacity=0.7)
        fig.update_layout(
            **_LAYOUT,
            title=title or self.title,
            xaxis_title="Strike",
            yaxis_title="Implied Volatility",
            barmode="group",
        )
        return fig
