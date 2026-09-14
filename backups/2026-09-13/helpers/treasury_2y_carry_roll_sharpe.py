"""2Y Treasury carry, roll, and rolling Sharpe via FRED."""
import os
import sys
from datetime import date
from math import sqrt

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "fred_client", ".env"))

_API_KEY = os.environ.get("FRED_API_KEY")
if not _API_KEY:
    sys.exit("FRED_API_KEY not set")

_BASE = "https://api.stlouisfed.org/fred/series/observations"
_START = "2000-01-01"

_PALETTE = {
    "carry": "#0057A8",
    "roll":  "#00875A",
    "sharpe": "#C8102E",
    "zero": "#CCCCCC",
}


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist={429, 500, 502, 503, 504})
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def fetch(series_id: str, sess: requests.Session, start: str = _START,
          resample: str | None = "ME") -> pd.Series:
    r = sess.get(_BASE, params={
        "series_id": series_id,
        "observation_start": start,
        "api_key": _API_KEY,
        "file_type": "json",
    })
    r.raise_for_status()
    obs = r.json()["observations"]
    s = pd.Series(
        {o["date"]: o["value"] for o in obs},
        name=series_id,
        dtype=object,
    )
    s.index = pd.to_datetime(s.index)
    s = pd.to_numeric(s, errors="coerce").dropna()
    if resample:
        s = s.resample(resample).last()
    return s


def _returns(dgs2: pd.Series, dgs1: pd.Series, dff: pd.Series,
             scale: int, price_chg: bool = False) -> pd.DataFrame:
    """Build carry/roll/tr frame. scale=252 for daily, 12 for monthly.
    price_chg=True adds -ModDur*ΔY for mark-to-market (daily only)."""
    df = pd.DataFrame({"DGS2": dgs2, "DGS1": dgs1, "DFF": dff}).dropna()
    df["carry"] = (df["DGS2"] - df["DFF"]) / scale / 100
    mod_dur     = 2 / (1 + df["DGS2"] / 200)
    df["roll"]  = mod_dur * (df["DGS2"] - df["DGS1"]) / scale / 100
    if price_chg:
        df["price_chg"] = -mod_dur * df["DGS2"].diff() / 100
        df["tr"] = df["carry"] + df["roll"] + df["price_chg"]
    else:
        df["tr"] = df["carry"] + df["roll"]
    return df.dropna()


def build_df() -> pd.DataFrame:
    sess = _session()
    dgs2 = fetch("DGS2", sess)
    dgs1 = fetch("DGS1", sess)
    dff  = fetch("DFF",  sess)
    df = _returns(dgs2, dgs1, dff, scale=12)
    df["sharpe_full"] = (df["tr"].mean() * 12) / (df["tr"].std() * sqrt(12))
    return df


def rolling_sharpe(lookback_days: int = 252, window: int = 30) -> pd.Series:
    """Daily (carry+roll)/vol using a rolling `window`-day window, over last `lookback_days`."""
    sess = _session()
    # fetch extra history so the first rolling window is valid at the start of lookback
    dgs2 = fetch("DGS2", sess, resample=None)
    dgs1 = fetch("DGS1", sess, resample=None)
    dff  = fetch("DFF",  sess, resample=None)
    daily = _returns(dgs2, dgs1, dff, scale=252, price_chg=True).iloc[-(lookback_days + window):]

    cr   = daily["carry"] + daily["roll"]
    tr   = daily["tr"]
    num  = cr.rolling(window).mean() * 252
    den  = tr.rolling(window).std() * sqrt(252)
    s    = (num / den).iloc[window:]          # drop burn-in
    return s.iloc[-lookback_days:]            # trim to requested lookback


def snap(days: int = 252) -> dict:
    """Point-in-time snapshot using daily data over the last `days` trading days.
    Sharpe = annualized (carry+roll) / annualized vol(total return incl. price chg)."""
    sess = _session()
    dgs2 = fetch("DGS2", sess, resample=None)
    dgs1 = fetch("DGS1", sess, resample=None)
    dff  = fetch("DFF",  sess, resample=None)
    daily = _returns(dgs2, dgs1, dff, scale=252, price_chg=True).iloc[-days:]
    latest = daily.iloc[-1]
    ann_carry_roll = (daily["carry"] + daily["roll"]).mean() * 252
    ann_vol        = daily["tr"].std() * sqrt(252)
    return {
        "date":        daily.index[-1].date(),
        "DGS2":        latest["DGS2"],
        "DGS1":        latest["DGS1"],
        "DFF":         latest["DFF"],
        "carry_daily": latest["carry"],
        "roll_daily":  latest["roll"],
        "ann_carry":   daily["carry"].mean() * 252,
        "ann_roll":    daily["roll"].mean() * 252,
        "ann_vol":     ann_vol,
        "sharpe":      ann_carry_roll / ann_vol if ann_vol else float("nan"),
        "days":        len(daily),
    }


def chart(df: pd.DataFrame, sharpe: float) -> go.Figure:
    fig = go.Figure()

    for comp, color, label in [
        ("carry", _PALETTE["carry"], "Carry"),
        ("roll",  _PALETTE["roll"],  "Roll"),
    ]:
        fig.add_trace(go.Bar(
            x=df.index,
            y=df[comp] * 100,
            name=label,
            marker_color=color,
            opacity=0.85,
        ))

    fig.update_layout(
        barmode="relative",
        template="none",
        font=dict(family="Helvetica Neue, Arial, sans-serif", size=12, color="#333333"),
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        height=480,
        margin=dict(t=90, b=40, l=60, r=40),
        title=dict(
            text=(
                f"<b>2-Year US Treasury: Carry & Roll</b>  "
                f"<span style='color:{_PALETTE['sharpe']};font-size:14px'>"
                f"Sharpe (1yr, C+R / σ): {sharpe:.2f}</span><br>"
                f"<span style='font-size:11px;color:#666'>FRED data · {date.today()}</span>"
            ),
            x=0,
            xanchor="left",
            font=dict(size=15),
        ),
    )

    fig.update_xaxes(showgrid=False, showline=True, linecolor="#CCCCCC")
    fig.update_yaxes(showgrid=True, gridcolor="#E5E5E5", zeroline=True,
                     zerolinecolor="#CCCCCC", ticksuffix="%", title_text="Monthly return (%)")

    return fig


def main() -> None:
    print("Computing 30d rolling (carry+roll)/vol over last year...")
    rs = rolling_sharpe(lookback_days=252, window=30)

    latest = rs.iloc[-1]
    print(f"  Latest ({rs.index[-1].date()}): {latest:.2f}")
    print(f"  Range: [{rs.min():.2f}, {rs.max():.2f}]  Mean: {rs.mean():.2f}")

    fig = go.Figure()
    fig.add_hline(y=0, line=dict(color="#CCCCCC", width=1, dash="dot"))
    fig.add_trace(go.Scatter(
        x=rs.index,
        y=rs.values,
        mode="lines",
        line=dict(color=_PALETTE["carry"], width=1.8),
        fill="tozeroy",
        fillcolor="rgba(0,87,168,0.12)",
        name="(Carry+Roll)/Vol",
    ))

    fig.update_layout(
        template="none",
        font=dict(family="Helvetica Neue, Arial, sans-serif", size=12, color="#333333"),
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        height=420,
        margin=dict(t=80, b=40, l=60, r=40),
        title=dict(
            text=(
                f"<b>2Y Treasury: 30d Rolling (Carry+Roll) / Vol</b>  "
                f"<span style='color:{_PALETTE['sharpe']}'>"
                f"Latest: {latest:.2f}</span><br>"
                f"<span style='font-size:11px;color:#666'>"
                f"Daily data, vol = σ(total return incl. price chg) · FRED · {date.today()}</span>"
            ),
            x=0, xanchor="left", font=dict(size=14),
        ),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor="#CCCCCC")
    fig.update_yaxes(showgrid=True, gridcolor="#E5E5E5", zeroline=False, title_text="Sharpe")

    out = f"treasury_2y_carry_roll_sharpe_{date.today()}.html"
    fig.write_html(out, include_plotlyjs="cdn")
    print(f"Saved → {out}")


if __name__ == "__main__":
    main()
