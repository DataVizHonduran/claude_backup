"""
Generate index.html with bar chart landing page, mode selector, and scatter tab.
Tab 1: Current Positioning bar charts (fast/slow modes)
Tab 2: Scatter — current positioning (Y) vs. N-day MA of positioning (X)
"""

import os
import json
from datetime import datetime
import plotly.graph_objects as go
import plotly.io as pio

OUTPUT_DIR = "reports/cta-signals"

# Load summary data
with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'r') as f:
    all_summaries = json.load(f)

# Get positions for both modes
fast_positions = all_summaries['fast']['latest_positions']
slow_positions = all_summaries['slow']['latest_positions']

# MA positions for scatter tab (empty dict if not yet generated)
fast_ma = all_summaries['fast'].get('ma_positions', {})
slow_ma = all_summaries['slow'].get('ma_positions', {})

# ── Bar charts ────────────────────────────────────────────────────────────────

def create_position_bar_chart(positions, mode):
    """Create interactive bar chart of current positions"""
    sorted_currencies = sorted(positions.keys(), key=lambda x: positions[x], reverse=True)
    currencies = sorted_currencies
    values = [positions[ccy] for ccy in currencies]
    colors = ['#28a745' if v > 0 else '#dc3545' for v in values]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=currencies,
        y=values,
        marker=dict(color=colors, line=dict(color='rgba(0,0,0,0.3)', width=1)),
        hovertemplate='<b>%{x}</b><br>Position: %{y:.1f}<extra></extra>',
        customdata=currencies
    ))

    fig.update_layout(
        title=dict(
            text=f"CTA {mode.upper()} Mode - Current Positioning",
            x=0.5, xanchor='center', font=dict(size=22, color='#333')
        ),
        xaxis=dict(title="Currency", showgrid=False, tickangle=-45, tickfont=dict(size=11)),
        yaxis=dict(title="Position Size", showgrid=True, gridcolor='#e9ecef',
                   zeroline=True, zerolinecolor='#333', zerolinewidth=2, range=[-55, 55]),
        plot_bgcolor='white',
        height=500,
        margin=dict(b=100),
        hovermode='closest'
    )
    return fig

fast_fig = create_position_bar_chart(fast_positions, 'fast')
slow_fig = create_position_bar_chart(slow_positions, 'slow')

fast_html = pio.to_html(fast_fig, include_plotlyjs=False, div_id='fast-chart')
slow_html = pio.to_html(slow_fig, include_plotlyjs=False, div_id='slow-chart')

# ── Assemble full HTML page ───────────────────────────────────────────────────
html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CTA Exhaustion Signals</title>
    <script src="https://cdn.plot.ly/plotly-2.26.0.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}

        .container {{ max-width: 1400px; margin: 0 auto; }}

        h1 {{
            color: #333;
            border-bottom: 3px solid #007bff;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }}

        h2 {{
            color: #333;
            margin-bottom: 15px;
            font-size: 1.3em;
        }}

        .info-box {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .methodology {{
            background: #e7f3ff;
            padding: 15px;
            border-left: 4px solid #007bff;
            margin-bottom: 20px;
            border-radius: 4px;
        }}

        .methodology h3 {{ margin: 0 0 10px 0; color: #007bff; }}
        .methodology p {{ margin: 5px 0; line-height: 1.6; }}

        /* ── Mode selector ── */
        .mode-selector {{
            display: flex;
            gap: 10px;
            margin-bottom: 16px;
            justify-content: center;
        }}

        .mode-btn {{
            padding: 12px 30px;
            font-size: 16px;
            font-weight: bold;
            border: 2px solid #007bff;
            background: white;
            color: #007bff;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.3s;
        }}

        .mode-btn:hover {{ background: #e7f3ff; }}
        .mode-btn.active {{ background: #007bff; color: white; }}

        /* ── Tab navigation ── */
        .tab-bar {{
            display: flex;
            gap: 3px;
            margin-bottom: 0;
            border-bottom: 2px solid #dee2e6;
        }}

        .tab-btn {{
            padding: 10px 24px;
            font-size: 14px;
            font-weight: 600;
            border: 1px solid #dee2e6;
            border-bottom: none;
            background: #f8f9fa;
            color: #495057;
            border-radius: 6px 6px 0 0;
            cursor: pointer;
            transition: background 0.15s, color 0.15s;
            margin-bottom: -2px;
        }}

        .tab-btn:hover {{ background: #e9ecef; }}
        .tab-btn.active {{
            background: white;
            color: #007bff;
            border-color: #dee2e6;
            border-bottom: 2px solid white;
        }}

        .tab-panel {{ display: none; padding-top: 20px; }}
        .tab-panel.active {{ display: block; }}

        /* ── Bar chart tab ── */
        .chart-container {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}

        .chart-wrapper {{ display: none; }}
        .chart-wrapper.active {{ display: block; }}

        /* ── Scatter tab ── */
        .scatter-controls {{
            background: white;
            padding: 14px 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 14px;
        }}

        .scatter-controls label {{
            font-weight: 600;
            color: #333;
            white-space: nowrap;
        }}

        #ma-n-select {{
            padding: 8px 16px;
            font-size: 15px;
            border: 2px solid #007bff;
            border-radius: 6px;
            background: white;
            color: #007bff;
            font-weight: 600;
            cursor: pointer;
            outline: none;
        }}

        #ma-n-select:focus {{ box-shadow: 0 0 0 3px rgba(0,123,255,0.25); }}

        /* ── Stats grid ── */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }}

        .stat-item {{
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
            text-align: center;
        }}

        .stat-label {{ font-size: 0.9em; color: #666; margin-bottom: 5px; }}
        .stat-value {{ font-size: 1.5em; font-weight: bold; color: #333; }}

        .last-updated {{ text-align: center; color: #666; font-size: 0.9em; margin-top: 20px; }}

        /* ── Currency link grid ── */
        .currency-list {{ margin-top: 20px; }}
        .currency-list h3 {{ margin-bottom: 15px; color: #333; }}

        .currency-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 10px;
        }}

        .currency-link {{
            display: block;
            padding: 10px;
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            text-decoration: none;
            color: #007bff;
            font-weight: 500;
            transition: all 0.2s;
            text-align: center;
        }}

        .currency-link:hover {{
            background: #e7f3ff;
            border-color: #007bff;
            transform: translateY(-2px);
            box-shadow: 0 2px 4px rgba(0,123,255,0.2);
        }}

        .position-badge {{
            display: inline-block;
            margin-left: 8px;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            font-weight: bold;
        }}

        .position-long  {{ background: #d4edda; color: #155724; }}
        .position-short {{ background: #f8d7da; color: #721c24; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 CTA Exhaustion Signals</h1>

        <div class="info-box">
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-label">Currencies Tracked</div>
                    <div class="stat-value">{all_summaries['fast']['currencies']}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Fast Mode Windows</div>
                    <div class="stat-value">{all_summaries['fast']['windows']}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Slow Mode Windows</div>
                    <div class="stat-value">{all_summaries['slow']['windows']}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Fast Signals (Total)</div>
                    <div class="stat-value">{all_summaries['fast'].get('signal_count', '—')}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Last Updated</div>
                    <div class="stat-value">{datetime.fromisoformat(all_summaries['fast']['generated_at']).strftime('%Y-%m-%d')}</div>
                </div>
            </div>
        </div>

        <div class="methodology">
            <h3>How It Works</h3>
            <p><strong>CTA Positioning:</strong> Measures momentum-following positioning using triple EMA convergence.
            Values range from -50 (max short) to +50 (max long).</p>
            <p><strong>Fast Mode:</strong> Uses 20/50/100 day EMAs for more responsive signals.</p>
            <p><strong>Slow Mode:</strong> Uses 50/100/200 day EMAs for longer-term trends.</p>
            <p><strong>Exhaustion Signals:</strong> Red markers on charts indicate when extreme positioning unwinds,
            suggesting potential trend exhaustion and reversal opportunities. Signals require rolling 2-year
            percentile confirmation, rate-of-change filter, and RSI of positioning confirmation.
            Numbers on markers show the signal strength score (0–100).</p>
        </div>

        <div class="mode-selector">
            <button class="mode-btn active" data-mode="fast" onclick="showMode('fast')">FAST Mode (20/50/100)</button>
            <button class="mode-btn" data-mode="slow" onclick="showMode('slow')">SLOW Mode (50/100/200)</button>
        </div>

        <div class="tab-bar">
            <button class="tab-btn active" data-tab="positions" onclick="switchTab('positions')">Current Positioning</button>
            <button class="tab-btn" data-tab="scatter" onclick="switchTab('scatter')">Positioning vs. MA</button>
            <button class="tab-btn" data-tab="quadrant" onclick="switchTab('quadrant')">Fast vs. Slow</button>
        </div>

        <!-- Tab 1: Bar charts -->
        <div id="tab-positions" class="tab-panel active">
            <div class="chart-container">
                <div id="fast-chart-wrapper" class="chart-wrapper active">
                    {fast_html}
                </div>
                <div id="slow-chart-wrapper" class="chart-wrapper">
                    {slow_html}
                </div>
            </div>

            <div class="currency-list">
                <h3>View Individual Currency Charts</h3>
                <div class="currency-grid" id="currency-grid"></div>
            </div>
        </div>

        <!-- Tab 2: Scatter — current positioning vs. N-day MA -->
        <div id="tab-scatter" class="tab-panel">
            <div class="scatter-controls">
                <label for="ma-n-select">Moving Average Window:</label>
                <select id="ma-n-select" onchange="renderScatterChart()">
                    <option value="5">5 days</option>
                    <option value="10">10 days</option>
                    <option value="20" selected>20 days</option>
                    <option value="50">50 days</option>
                    <option value="60">60 days</option>
                    <option value="100">100 days</option>
                    <option value="200">200 days</option>
                </select>
            </div>
            <div class="chart-container">
                <div id="scatter-chart" style="height:580px; width:100%;"></div>
            </div>
        </div>

        <!-- Tab 3: Fast vs. Slow divergence quadrant -->
        <div id="tab-quadrant" class="tab-panel">
            <div class="chart-container">
                <div id="quadrant-chart" style="height:580px; width:100%;"></div>
            </div>
        </div>

        <div class="last-updated">
            Last updated: {datetime.fromisoformat(all_summaries['fast']['generated_at']).strftime('%Y-%m-%d %H:%M UTC')}
        </div>
    </div>

    <script>
        let currentMode = 'fast';

        const fastPositions = {json.dumps(fast_positions)};
        const slowPositions = {json.dumps(slow_positions)};
        const maData = {{
            fast: {json.dumps(fast_ma)},
            slow: {json.dumps(slow_ma)}
        }};

        // ── Mode selector ─────────────────────────────────────────────────────
        function showMode(mode) {{
            currentMode = mode;

            document.querySelectorAll('.mode-btn').forEach(btn => {{
                btn.classList.toggle('active', btn.dataset.mode === mode);
            }});

            // Update bar chart visibility
            document.querySelectorAll('.chart-wrapper').forEach(w => w.classList.remove('active'));
            const activeWrapper = document.getElementById(mode + '-chart-wrapper');
            if (activeWrapper) {{
                activeWrapper.classList.add('active');
                setTimeout(() => {{
                    const chartDiv = activeWrapper.querySelector('[id$="-chart"]');
                    if (chartDiv && window.Plotly) Plotly.Plots.resize(chartDiv);
                }}, 50);
            }}

            updateCurrencyGrid();

            // Re-render scatter if that tab is active
            if (document.getElementById('tab-scatter').classList.contains('active')) {{
                renderScatterChart();
            }}
        }}

        // ── Tab switching ─────────────────────────────────────────────────────
        function switchTab(tab) {{
            document.querySelectorAll('.tab-btn').forEach(btn => {{
                btn.classList.toggle('active', btn.dataset.tab === tab);
            }});
            document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.remove('active'));
            document.getElementById('tab-' + tab).classList.add('active');

            if (tab === 'scatter') {{
                renderScatterChart();
            }}
            if (tab === 'quadrant') {{
                renderQuadrantChart();
            }}
        }}

        // ── Currency grid (bar chart tab) ─────────────────────────────────────
        function getSortedCurrencies(positions) {{
            return Object.keys(positions).sort((a, b) => positions[b] - positions[a]);
        }}

        function updateCurrencyGrid() {{
            const positions = currentMode === 'fast' ? fastPositions : slowPositions;
            const sortedCurrencies = getSortedCurrencies(positions);
            const grid = document.getElementById('currency-grid');

            grid.innerHTML = sortedCurrencies.map(ccy => {{
                const pos = positions[ccy];
                const badge = pos > 0
                    ? `<span class="position-badge position-long">+${{pos.toFixed(1)}}</span>`
                    : `<span class="position-badge position-short">${{pos.toFixed(1)}}</span>`;
                return `<a href="${{ccy}}_exhaustion_${{currentMode}}.html" class="currency-link">${{ccy}}${{badge}}</a>`;
            }}).join('');
        }}

        // ── Scatter chart ─────────────────────────────────────────────────────
        function renderScatterChart() {{
            const n = document.getElementById('ma-n-select').value;
            const ma   = (maData[currentMode] && maData[currentMode][n]) || {{}};
            const curr = currentMode === 'fast' ? fastPositions : slowPositions;

            const currencies = Object.keys(curr).filter(c => c in ma);
            currencies.sort((a, b) => curr[b] - curr[a]);

            if (currencies.length === 0) {{
                document.getElementById('scatter-chart').innerHTML =
                    '<p style="text-align:center;padding:60px;color:#666;font-size:1.1em">' +
                    'MA data not yet available. Run <code>python3 scripts/patch_ma_positions.py</code> ' +
                    'then <code>python3 scripts/generate_index.py</code>.</p>';
                return;
            }}

            const x = currencies.map(c => ma[c]);
            const y = currencies.map(c => curr[c]);
            const colors = y.map(v => v > 0.5 ? '#28a745' : v < -0.5 ? '#dc3545' : '#6c757d');
            const sizes  = y.map(v => Math.max(9, Math.min(22, Math.abs(v) * 0.28 + 9)));

            const AX = [-55, 55];

            const traces = [
                // Dashed diagonal: y = x (current = MA, no divergence)
                {{
                    x: AX, y: AX,
                    mode: 'lines',
                    line: {{color: '#adb5bd', width: 1.5, dash: 'dot'}},
                    hoverinfo: 'none',
                    showlegend: false
                }},
                // Currency scatter points
                {{
                    x, y,
                    mode: 'markers+text',
                    text: currencies,
                    textposition: y.map(v => v >= 0 ? 'top center' : 'bottom center'),
                    textfont: {{size: 11, color: '#333'}},
                    marker: {{
                        color: colors,
                        size: sizes,
                        opacity: 0.85,
                        line: {{color: 'rgba(0,0,0,0.25)', width: 1}}
                    }},
                    customdata: currencies,
                    hovertemplate:
                        '<b>%{{customdata}}</b><br>' +
                        'Current: %{{y:.1f}}<br>' +
                        n + '-day MA: %{{x:.1f}}<extra></extra>',
                    showlegend: false
                }}
            ];

            const layout = {{
                title: {{
                    text: `CTA ${{currentMode.toUpperCase()}} \u2014 Current Positioning vs. ${{n}}-Day MA`,
                    x: 0.5, xanchor: 'center',
                    font: {{size: 20, color: '#333'}}
                }},
                xaxis: {{
                    title: `${{n}}-Day Moving Average of Positioning`,
                    range: AX,
                    showgrid: true, gridcolor: '#e9ecef',
                    zeroline: true, zerolinecolor: '#999', zerolinewidth: 1.5
                }},
                yaxis: {{
                    title: 'Current Positioning',
                    range: AX,
                    showgrid: true, gridcolor: '#e9ecef',
                    zeroline: true, zerolinecolor: '#999', zerolinewidth: 1.5
                }},
                annotations: [
                    {{x: 44, y: 51, xanchor: 'right', yanchor: 'top',
                      text: 'Long \u00b7 above avg', showarrow: false,
                      font: {{color: '#adb5bd', size: 10}}}},
                    {{x: -44, y: 51, xanchor: 'left', yanchor: 'top',
                      text: 'Recovering \u00b7 long', showarrow: false,
                      font: {{color: '#adb5bd', size: 10}}}},
                    {{x: 44, y: -51, xanchor: 'right', yanchor: 'bottom',
                      text: 'Fading \u00b7 long avg', showarrow: false,
                      font: {{color: '#adb5bd', size: 10}}}},
                    {{x: -44, y: -51, xanchor: 'left', yanchor: 'bottom',
                      text: 'Short \u00b7 below avg', showarrow: false,
                      font: {{color: '#adb5bd', size: 10}}}}
                ],
                plot_bgcolor: 'white',
                height: 580,
                hovermode: 'closest',
                margin: {{t: 60, l: 65, r: 30, b: 65}}
            }};

            Plotly.react('scatter-chart', traces, layout, {{responsive: true}});
        }}

        // ── Quadrant chart: fast (Y) vs. slow (X) ────────────────────────────
        function renderQuadrantChart() {{
            const currencies = Object.keys(fastPositions).filter(c => c in slowPositions);

            const x = currencies.map(c => slowPositions[c]);
            const y = currencies.map(c => fastPositions[c]);

            const colors = currencies.map(c => {{
                const f = fastPositions[c], s = slowPositions[c];
                if (f > 0 && s > 0) return '#28a745';
                if (f < 0 && s < 0) return '#dc3545';
                return '#fd7e14';
            }});

            const sizes = currencies.map(c => {{
                const mag = Math.sqrt(fastPositions[c] ** 2 + slowPositions[c] ** 2);
                return Math.max(9, Math.min(24, mag * 0.25 + 9));
            }});

            const AX = [-55, 55];

            const traces = [
                {{
                    x: AX, y: AX,
                    mode: 'lines',
                    line: {{color: '#adb5bd', width: 1.5, dash: 'dot'}},
                    hoverinfo: 'none',
                    showlegend: false
                }},
                {{
                    x, y,
                    mode: 'markers+text',
                    text: currencies,
                    textposition: y.map(v => v >= 0 ? 'top center' : 'bottom center'),
                    textfont: {{size: 11, color: '#333'}},
                    marker: {{
                        color: colors,
                        size: sizes,
                        opacity: 0.85,
                        line: {{color: 'rgba(0,0,0,0.25)', width: 1}}
                    }},
                    customdata: currencies,
                    hovertemplate: '<b>%{{customdata}}</b><br>Slow: %{{x:.1f}}<br>Fast: %{{y:.1f}}<extra></extra>',
                    showlegend: false
                }}
            ];

            const layout = {{
                title: {{
                    text: 'CTA Fast vs. Slow — Signal Divergence',
                    x: 0.5, xanchor: 'center',
                    font: {{size: 20, color: '#333'}}
                }},
                xaxis: {{
                    title: 'Slow Signal (50/100/200)',
                    range: AX,
                    showgrid: true, gridcolor: '#e9ecef',
                    zeroline: true, zerolinecolor: '#999', zerolinewidth: 1.5
                }},
                yaxis: {{
                    title: 'Fast Signal (20/50/100)',
                    range: AX,
                    showgrid: true, gridcolor: '#e9ecef',
                    zeroline: true, zerolinecolor: '#999', zerolinewidth: 1.5
                }},
                annotations: [
                    {{x: 44, y: 51, xanchor: 'right', yanchor: 'top',
                      text: 'Both Long', showarrow: false,
                      font: {{color: '#28a745', size: 11}}}},
                    {{x: -44, y: 51, xanchor: 'left', yanchor: 'top',
                      text: 'Fast Long · Slow Short', showarrow: false,
                      font: {{color: '#fd7e14', size: 11}}}},
                    {{x: 44, y: -51, xanchor: 'right', yanchor: 'bottom',
                      text: 'Fast Short · Slow Long', showarrow: false,
                      font: {{color: '#fd7e14', size: 11}}}},
                    {{x: -44, y: -51, xanchor: 'left', yanchor: 'bottom',
                      text: 'Both Short', showarrow: false,
                      font: {{color: '#dc3545', size: 11}}}}
                ],
                plot_bgcolor: 'white',
                height: 580,
                hovermode: 'closest',
                margin: {{t: 60, l: 65, r: 30, b: 65}}
            }};

            Plotly.react('quadrant-chart', traces, layout, {{responsive: true}});
        }}

        // ── Init ──────────────────────────────────────────────────────────────
        document.addEventListener('DOMContentLoaded', function() {{
            updateCurrencyGrid();

            const charts = document.querySelectorAll('[id$="-chart"]');
            charts.forEach(chart => {{
                chart.on('plotly_click', function(data) {{
                    if (!data.points[0].customdata) return;
                    const ccy = data.points[0].customdata;
                    window.location.href = `${{ccy}}_exhaustion_${{currentMode}}.html`;
                }});
            }});
        }});
    </script>
</body>
</html>
"""

# Write index.html
with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w') as f:
    f.write(html_content)

print(f"✅ Generated index.html with bar charts for {len(fast_positions)} currencies")
print(f"   - FAST mode chart with {all_summaries['fast']['windows']} windows")
print(f"   - SLOW mode chart with {all_summaries['slow']['windows']} windows")
print(f"   - Scatter tab: {'MA data present' if fast_ma else 'no MA data (run patch_ma_positions.py)'}")
