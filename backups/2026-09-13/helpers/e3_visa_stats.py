import io
import requests
import pandas as pd
import plotly.graph_objects as go

URL = "https://travel.state.gov/content/dam/visas/Statistics/Non-Immigrant-Statistics/NIVDetailTables/FYs97-24_NIVDetailTable.xlsx"

print("Downloading NIV detail table...")
r = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
r.raise_for_status()

xl = pd.ExcelFile(io.BytesIO(r.content))

records = []
for sheet in xl.sheet_names:
    fy_label = sheet  # e.g. "FY05"
    fy_num = int(sheet[2:])
    fiscal_year = 2000 + fy_num if fy_num < 50 else 1900 + fy_num

    df = xl.parse(sheet, header=None)

    # Row 0 is the header
    header = df.iloc[0].tolist()

    # Find E-3 and E-3D column indices (FY22+ uses no hyphens: "E3"/"E3D")
    def match_class(h, name):
        normalized = str(h).strip().replace("-", "")
        return normalized == name.replace("-", "")

    e3_idx = next((i for i, h in enumerate(header) if match_class(h, "E-3") and not match_class(h, "E-3D") and not match_class(h, "E-3R")), None)
    e3d_idx = next((i for i, h in enumerate(header) if match_class(h, "E-3D")), None)

    if e3_idx is None:
        # Pre-2005: E-3 didn't exist
        records.append({"fiscal_year": fiscal_year, "e3_principal": 0, "e3_dependent": 0})
        continue

    # Find "Grand Total" row
    data_rows = df.iloc[1:].reset_index(drop=True)
    country_col = data_rows.iloc[:, 0].astype(str).str.strip()
    grand_total_mask = country_col.str.lower().str.contains("grand total")

    if grand_total_mask.any():
        row = data_rows[grand_total_mask].iloc[0]
        e3_val = pd.to_numeric(row.iloc[e3_idx], errors="coerce") or 0
        e3d_val = pd.to_numeric(row.iloc[e3d_idx], errors="coerce") if e3d_idx else 0
    else:
        e3_val = pd.to_numeric(data_rows.iloc[:, e3_idx], errors="coerce").sum()
        e3d_val = pd.to_numeric(data_rows.iloc[:, e3d_idx], errors="coerce").sum() if e3d_idx else 0

    records.append({
        "fiscal_year": fiscal_year,
        "e3_principal": int(e3_val or 0),
        "e3_dependent": int(e3d_val or 0),
    })

df_out = pd.DataFrame(records).sort_values("fiscal_year").reset_index(drop=True)
df_out["total"] = df_out["e3_principal"] + df_out["e3_dependent"]

# Drop years before E-3 existed
df_out = df_out[df_out["total"] > 0]

df_out["cumulative_total"] = df_out["total"].cumsum()
df_out["cumulative_principal"] = df_out["e3_principal"].cumsum()
df_out["cumulative_dependent"] = df_out["e3_dependent"].cumsum()

print(df_out[["fiscal_year", "e3_principal", "e3_dependent", "total", "cumulative_total"]].to_string(index=False))

# Save CSV
df_out.to_csv("e3_visa_usage.csv", index=False)
print("\nSaved e3_visa_usage.csv")

# Chart — cumulative area
fig = go.Figure()

fig.add_trace(go.Scatter(
    x=df_out["fiscal_year"],
    y=df_out["cumulative_principal"],
    name="E-3 Principal",
    fill="tozeroy",
    mode="lines",
    line=dict(color="#1f77b4", width=2),
    fillcolor="rgba(31,119,180,0.5)",
))

fig.add_trace(go.Scatter(
    x=df_out["fiscal_year"],
    y=df_out["cumulative_total"],
    name="E-3 + Dependents",
    fill="tonexty",
    mode="lines",
    line=dict(color="#aec7e8", width=2),
    fillcolor="rgba(174,199,232,0.4)",
))

fig.update_layout(
    title="E-3 Visa Cumulative Issuances FY2005–2024 (State Dept consular data)",
    xaxis_title="Fiscal Year",
    yaxis_title="Cumulative Visas Issued",
    xaxis=dict(dtick=1),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    template="plotly_white",
    height=520,
)

fig.write_html("e3_visa_usage.html")
print("Saved e3_visa_usage.html")
