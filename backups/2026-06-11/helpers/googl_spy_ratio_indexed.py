import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

data = yf.download(["GOOGL", "SPY"], start="2005-01-01", auto_adjust=True, progress=False)
close = data["Close"]

ratio = close["GOOGL"] / close["SPY"]
ratio = ratio.dropna()

base = ratio["2010-01-01":"2010-01-31"].iloc[0]
indexed = (ratio / base) * 100

fig, ax = plt.subplots(figsize=(13, 6))
fig.patch.set_facecolor("#0d1117")
ax.set_facecolor("#0d1117")

# recession bands
recessions = [("2007-12-01", "2009-06-30"), ("2020-02-01", "2020-04-30")]
for start, end in recessions:
    ax.axvspan(pd.Timestamp(start), pd.Timestamp(end), color="#ff4444", alpha=0.12, zorder=0)

ax.axhline(100, color="#555555", linewidth=0.8, linestyle="--", zorder=1)

ax.plot(indexed.index, indexed.values, color="#00d4ff", linewidth=1.4, zorder=2)

ax.fill_between(indexed.index, indexed.values, 100,
                where=(indexed.values >= 100), color="#00d4ff", alpha=0.07)
ax.fill_between(indexed.index, indexed.values, 100,
                where=(indexed.values < 100), color="#ff6b35", alpha=0.10)

ax.set_title("GOOGL / SPY Ratio  —  Indexed to 100 at Jan 2010", color="white",
             fontsize=14, fontweight="bold", pad=14)
ax.set_ylabel("Index (100 = Jan 2010)", color="#aaaaaa", fontsize=10)
ax.tick_params(colors="#aaaaaa")
for spine in ax.spines.values():
    spine.set_edgecolor("#333333")

ax.xaxis.set_major_locator(mdates.YearLocator(2))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.xaxis.set_minor_locator(mdates.YearLocator(1))

current_val = indexed.iloc[-1]
ax.annotate(f"{current_val:.1f}", xy=(indexed.index[-1], current_val),
            xytext=(-48, 8), textcoords="offset points",
            color="#00d4ff", fontsize=9, fontweight="bold")

ax.text(0.01, 0.03, "Shaded: recessions (2008–09, COVID-2020)",
        transform=ax.transAxes, color="#666666", fontsize=8)

plt.tight_layout()
out = "googl_spy_ratio_indexed.png"
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
print(f"Saved: {out}  |  Current value: {current_val:.1f}")
