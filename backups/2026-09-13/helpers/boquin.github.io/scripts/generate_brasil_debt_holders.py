"""
Brazil DPF Debt Holders Dashboard
Generates an 8-panel Plotly chart (2 rows × 4 cols) showing:
  Row 1: R$ billions by holder type
  Row 2: % of total DPF by holder type
Followed by a 4-column structural analysis section below the chart.
Source: Relatório Mensal da Dívida (RMD) — Tesouro Nacional
"""

import io
import os
import zipfile

import pandas as pd
import plotly.graph_objects as go
import requests
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ZIP_URL = "https://thot-arquivos.tesouro.gov.br/publicacao-anexo/27925"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports", "brasil-debt-holders")
OUT_FILE = os.path.join(OUT_DIR, "index.html")

COLORS = {
    "banks":      "#0072B2",
    "funds":      "#009E73",
    "pensions":   "#D55E00",
    "foreigners": "#CC79A7",
}

HOLDERS = [
    ("banks",      "Instituições Financeiras", "Banks"),
    ("funds",      "Fundos de Investimento",   "Funds"),
    ("pensions",   "Previdência",               "Pensions"),
    ("foreigners", "Não-residentes",            "Foreigners"),
]

COL_MAP = {
    "banks":      (1, 2),
    "funds":      (3, 4),
    "pensions":   (5, 6),
    "foreigners": (7, 8),
    "total_brl":  15,
}

# ---------------------------------------------------------------------------
# Analysis text — one entry per holder, matching chart column order
# ---------------------------------------------------------------------------
ANALYSIS = {
    "banks": {
        "headline": "Why did bank holdings increase in 2019?",
        "factors": [
            ("Basel III LCR reached 100% (Jan 2019)",
             "CMN Resolution 4.401/2015 phased in the Liquidity Coverage Ratio in annual steps, reaching 100% in January 2019. Banks must hold High Quality Liquid Assets equal to 100% of projected 30-day stressed outflows — and HQLA in Brazil is almost entirely federal securities (LFTs, LTNs, NTN-Bs)."),
            ("Pension reform spread compression",
             "Bolsonaro's pension reform (approved October 2019) materially reduced long-term fiscal risk. Banks had been light on government bonds following the Dilma crisis of 2014-2016."),
            ("Subdued credit demand",
             "Private sector credit growth remained sluggish starting in 2019 as corporates found more attractive funding opportunities in the debentures market due to retail tax incentives."),
        ],
    },
    "funds": {
        "headline": "Why did fund holdings top out around 2019?",
        "factors": [
            ("Fixed income fund outflows (Selic collapse)",
             "The easing cycle (2.0% in 2020) collapsed returns on DI/renda fixa funds, which predominantly hold LFTs. The entire fixed income fund industry had been built around double digit Selic."),
            ("Rotation to equities and FIIs",
             "2019 was a record year for the Ibovespa and a boom year for Fundos de Investimento Imobiliário (FIIs). Capital that previously sat in DI funds recycled into equity funds, FIIs, and multi-market funds chasing higher returns."),
            ("CRI/CRA and debenture substitution",
             "Within fixed income mandates that remained, managers shifted from government bonds to higher-yielding tax-exempt instruments: CRIs (real estate receivables), CRAs (agribusiness receivables), and debentures incentivadas. These offer better after-tax yields than LTNs/NTN-Bs for the same duration risk, and the market grew rapidly from 2017 onward."),
            ("Tesouro Direto disintermediation",
             "As Selic fell, paying 0.5–1.0% annual management fees on a DI fund earning 4–6% became hard to justify. Retail investors shifted to buying LFTs and NTN-Bs directly via Tesouro Direto (TD), bypassing funds entirely. Registered TD investors grew from ~1.5M to 3M+ between 2018 and 2020."),
        ],
    },
    "pensions": {
        "headline": "Why did pension holdings surge after 2016?",
        "factors": [
            ("Selic and NTN-B yields beat actuarial targets",
             "Pension funds must earn INPC/IPCA + ~5–6%/year to meet actuarial benchmarks. With NTN-B real yields well above those targets, there was no reason to take credit or equity risk."),
            ("PREVIC de-risking mandates",
             "Many large funds posted massive deficits as equity portfolios collapsed. PREVIC required deficit funds to file formal recovery plans (planos de equacionamento) mandating minimum government bond allocation floors. This converted a voluntary gradual reallocation into a mandatory accelerated one."),
            ("FUNPRESP structural growth",
             "The complementary pension fund for federal civil servants (created 2013) reached meaningful AUM scale by 2015–2016. By design it invests predominantly in federal securities, adding a steady policy-driven bid for DPF that did not exist before 2013."),
        ],
    },
    "foreigners": {
        "headline": "Why did foreign holdings top out in 2016?",
        "factors": [
            ("BRL depreciation destroyed FX returns",
             "The BRL collapsed from ~R$2.20/USD in 2013 to ~R$4.00 by early 2016."),
            ("Sovereign downgrade and political risk",
             "S&P downgraded Brazil to junk in September 2015; Moody's followed in February 2016. Many institutional mandates have hard floors prohibiting sub-investment-grade holdings, triggering forced selling."),
         ],
    },
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def fetch_data():
    print("Fetching ZIP from Tesouro Nacional...", flush=True)
    resp = requests.get(ZIP_URL, timeout=120)
    resp.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    xlsx_name = next(n for n in zf.namelist() if n.endswith(".xlsx"))
    print(f"  Parsing: {xlsx_name}", flush=True)

    xl = pd.ExcelFile(zf.open(xlsx_name))
    sheet = next(s for s in xl.sheet_names if "2.7" in s)
    raw = xl.parse(sheet, header=None)

    data = raw.iloc[5:].copy()
    data.columns = range(data.shape[1])

    dates = pd.to_datetime(data[0], errors="coerce")
    data = data[dates.notna()].copy()
    dates = dates[dates.notna()]

    df = pd.DataFrame(index=dates)
    df.index.name = "date"

    for key, (brl_col, pct_col) in [(k, v) for k, v in COL_MAP.items() if k != "total_brl"]:
        df[f"{key}_brl"] = pd.to_numeric(data[brl_col].values, errors="coerce")
        df[f"{key}_pct"] = pd.to_numeric(data[pct_col].values, errors="coerce") * 100

    df["total_brl"] = pd.to_numeric(data[COL_MAP["total_brl"]].values, errors="coerce")
    df = df.sort_index().dropna(how="all")
    print(f"  Loaded {len(df)} monthly observations: {df.index[0]:%b %Y} – {df.index[-1]:%b %Y}")
    return df


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
def build_chart(df):
    subtitle_titles = []
    for key, pt_label, en_label in HOLDERS:
        subtitle_titles.append(f"<b>{en_label}</b><br><span style='font-size:11px;color:#666'>{pt_label}</span>")
    subtitle_titles += [""] * 4

    fig = make_subplots(
        rows=2, cols=4,
        shared_xaxes=True,
        vertical_spacing=0.12,
        horizontal_spacing=0.06,
        subplot_titles=subtitle_titles,
    )

    for col_idx, (key, pt_label, en_label) in enumerate(HOLDERS, start=1):
        color = COLORS[key]
        latest_date = df.index[-1]

        brl = df[f"{key}_brl"]
        fig.add_trace(go.Scatter(
            x=df.index, y=brl, mode="lines",
            line=dict(color=color, width=2), name=en_label, showlegend=False,
            hovertemplate="%{x|%b %Y}<br><b>R$ %{y:,.0f}bn</b><extra></extra>",
        ), row=1, col=col_idx)
        fig.add_annotation(
            x=latest_date, y=brl.iloc[-1],
            text=f"<b>R${brl.iloc[-1]:,.0f}bn</b>",
            xanchor="right", yanchor="bottom", showarrow=False,
            font=dict(size=10, color=color), row=1, col=col_idx,
        )

        pct = df[f"{key}_pct"]
        fig.add_trace(go.Scatter(
            x=df.index, y=pct, mode="lines",
            line=dict(color=color, width=2), name=en_label, showlegend=False,
            hovertemplate="%{x|%b %Y}<br><b>%{y:.1f}%</b><extra></extra>",
        ), row=2, col=col_idx)
        fig.add_annotation(
            x=latest_date, y=pct.iloc[-1],
            text=f"<b>{pct.iloc[-1]:.1f}%</b>",
            xanchor="right", yanchor="bottom", showarrow=False,
            font=dict(size=10, color=color), row=2, col=col_idx,
        )

    for row, label in [(1, "R$ Billions"), (2, "% of Total DPF")]:
        fig.add_annotation(
            text=f"<b>{label}</b>", xref="paper", yref="paper",
            x=-0.02, y=0.75 if row == 1 else 0.22,
            showarrow=False, font=dict(size=11, color="#444"), textangle=-90,
        )

    last_date_str = df.index[-1].strftime("%B %Y")
    fig.update_layout(
        title=dict(
            text=(f"<b>Holders of Brazil's Federal Public Debt (DPF)</b>"
                  f"<br><span style='font-size:13px;color:#666'>"
                  f"Monthly, R$ Billions and % of Total | Jan 2007 – {last_date_str}</span>"),
            x=0.5, xanchor="center", font=dict(size=18),
        ),
        height=700, width=1400,
        paper_bgcolor="white", plot_bgcolor="white",
        margin=dict(l=70, r=30, t=110, b=80),
        font=dict(family="Arial, sans-serif", size=11),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#e8e8e8", gridwidth=1,
                     tickformat="%Y", tickangle=0, tickfont=dict(size=9),
                     linecolor="#ccc", showline=True)
    fig.update_yaxes(showgrid=True, gridcolor="#e8e8e8", gridwidth=1,
                     tickfont=dict(size=9), linecolor="#ccc", showline=True, zeroline=False)
    for col_idx in range(1, 5):
        fig.update_yaxes(ticksuffix="%", row=2, col=col_idx)
    fig.add_annotation(
        text="Source: Tesouro Nacional — Relatório Mensal da Dívida (RMD), Anexo 2.7",
        xref="paper", yref="paper", x=0, y=-0.08,
        showarrow=False, font=dict(size=10, color="#888"), xanchor="left",
    )
    return fig


# ---------------------------------------------------------------------------
# Analysis HTML
# ---------------------------------------------------------------------------
def build_analysis_html():
    cols_html = ""
    for key, pt_label, en_label in HOLDERS:
        color = COLORS[key]
        info = ANALYSIS[key]
        factors_html = ""
        for label, text in info["factors"]:
            factors_html += f"""
            <div class="factor">
              <div class="factor-header">
                <span class="factor-label">{label}</span>
              </div>
              <p>{text}</p>
            </div>"""

        cols_html += f"""
        <div class="analysis-col">
          <div class="col-header" style="border-top: 3px solid {color};">
            <span class="col-title" style="color:{color}">{en_label}</span>
            <span class="col-subtitle">{pt_label}</span>
          </div>
          <h3 class="col-headline">{info['headline']}</h3>
          {factors_html}
        </div>"""

    return f"""
<div class="analysis-section">
  <h2 class="analysis-title">Structural Analysis</h2>
  <p class="analysis-note">Qualitative decomposition of key inflection points. Contribution estimates based on order-of-magnitude reasoning; precise decomposition would require fund-level portfolio data.</p>
  <div class="analysis-grid">
    {cols_html}
  </div>
</div>"""


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
CSS = """
* { box-sizing: border-box; }
body { font-family: Arial, sans-serif; background: #fff; color: #1a1a1a; }
.analysis-section { max-width: 1440px; margin: 0 auto; padding: 32px 16px 48px; }
.analysis-title { font-size: 22px; font-weight: 700; margin-bottom: 6px; color: #111; }
.analysis-note { font-size: 13px; color: #888; margin-bottom: 24px; }
.analysis-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px; }
.analysis-col { background: #fafafa; border-radius: 8px; padding: 20px; }
.col-header { padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid #e8e8e8; }
.col-title { display: block; font-size: 18px; font-weight: 700; }
.col-subtitle { display: block; font-size: 12px; color: #888; margin-top: 2px; }
.col-headline { font-size: 14px; font-weight: 600; color: #333; margin-bottom: 16px;
                line-height: 1.4; font-style: italic; }
.factor { margin-bottom: 18px; }
.factor:last-child { margin-bottom: 0; }
.factor-header { display: flex; justify-content: space-between; align-items: baseline;
                 margin-bottom: 4px; gap: 8px; }
.factor-label { font-size: 13px; font-weight: 600; color: #222; flex: 1; }
.factor-pct { font-size: 13px; font-weight: 700; white-space: nowrap; }
.factor p { font-size: 12.5px; color: #555; line-height: 1.55; }
@media (max-width: 900px) { .analysis-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 520px) { .analysis-grid { grid-template-columns: 1fr; } }
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    df = fetch_data()
    fig = build_chart(df)
    analysis_html = build_analysis_html()

    os.makedirs(OUT_DIR, exist_ok=True)

    # Let Plotly write the chart HTML cleanly, then inject analysis + CSS before </body>
    fig.write_html(OUT_FILE, include_plotlyjs="cdn")

    with open(OUT_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    inject = f"<style>{CSS}</style>\n{analysis_html}\n"
    html = html.replace("</body>", inject + "</body>")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nChart saved to: {os.path.abspath(OUT_FILE)}")


if __name__ == "__main__":
    main()
