#!/usr/bin/env python3
"""
NYRR Registration Timeline Watcher
Monitors nyrr.org/run/race-calendar/race-registration-launch-timeline for changes.
Outputs reports/nyrr/index.html to boquin.xyz; state persisted in data/nyrr_timeline_state.json.

Usage:
    python scripts/nyrr_watcher.py
    python scripts/nyrr_watcher.py --dry-run   # fetch + render but don't write
"""

import argparse
import difflib
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
TIMELINE_URL = "https://www.nyrr.org/run/race-calendar/race-registration-launch-timeline"
REPO_ROOT = Path(__file__).parent.parent
STATE_FILE = REPO_ROOT / "data" / "nyrr_timeline_state.json"
OUTPUT_FILE = REPO_ROOT / "reports" / "nyrr" / "index.html"
# ---------------------------------------------------------------------------


def fetch_timeline() -> str:
    """Return visible text of the NYRR registration launch timeline section."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        try:
            page.goto(TIMELINE_URL, wait_until="networkidle", timeout=45_000)
        except PlaywrightTimeout:
            # Site might still have partial content — continue
            pass

        # Detect virtual waiting room redirect
        if "virtualcorral.nyrr.org" in page.url or "queue" in page.url.lower():
            browser.close()
            raise RuntimeError(
                f"NYRR site is in virtual queue mode (redirected to {page.url}). "
                "Try again outside peak hours."
            )

        # Try to grab the main content area; fall back to full body text
        content = ""
        for selector in [
            "main",
            "[class*='content']",
            "[class*='race-calendar']",
            "article",
            "body",
        ]:
            el = page.query_selector(selector)
            if el:
                content = el.inner_text().strip()
                if len(content) > 200:
                    break

        browser.close()

    if not content:
        raise RuntimeError("Could not extract any content from the NYRR page.")

    # Strip noisy repeated whitespace
    lines = [ln.strip() for ln in content.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"hash": "", "content": "", "last_changed": None, "changelog": []}


def save_state(state: dict, dry_run: bool) -> None:
    if dry_run:
        return
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def compute_diff_summary(old: str, new: str) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    if not diff:
        return ""
    added = [ln[1:] for ln in diff if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln[1:] for ln in diff if ln.startswith("-") and not ln.startswith("---")]
    parts = []
    if added:
        parts.append("Added:\n" + "\n".join(f"  + {l}" for l in added[:10]))
    if removed:
        parts.append("Removed:\n" + "\n".join(f"  - {l}" for l in removed[:10]))
    return "\n".join(parts)


def render_html(state: dict, now_str: str) -> str:
    last_changed = state.get("last_changed") or "Never detected"
    try:
        changed_dt = datetime.fromisoformat(last_changed)
        changed_age_days = (datetime.now(timezone.utc) - changed_dt).days
        changed_label = changed_dt.strftime("%B %d, %Y")
        highlight_class = "highlight-recent" if changed_age_days <= 7 else ""
    except Exception:
        changed_label = last_changed
        highlight_class = ""
        changed_age_days = 999

    changelog = state.get("changelog", [])
    changelog_rows = ""
    for entry in reversed(changelog[-20:]):
        diff_html = entry.get("diff", "").replace("<", "&lt;").replace(">", "&gt;")
        diff_block = f'<pre class="diff-block">{diff_html}</pre>' if diff_html else ""
        changelog_rows += f"""
        <div class="changelog-entry">
            <span class="changelog-date">{entry['date']}</span>
            <span class="changelog-msg">{entry.get('summary', 'Content changed')}</span>
            {diff_block}
        </div>"""

    if not changelog_rows:
        changelog_rows = '<p class="muted">No changes detected yet.</p>'

    content_html = (
        state.get("content", "No content fetched yet.")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    changelog_section = changelog_rows if changelog_rows else (
        '<div class="empty-state"><span>🌱</span>No changes detected yet.</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NYRR Registration Timeline — boquin.xyz</title>
    <link rel="stylesheet" href="../../styles.css">
    <style>
        body {{ background: #fff9f5; }}
        .page-hero {{
            background: linear-gradient(135deg, #ff6b35 0%, #f7931e 100%);
            border-radius: 16px; padding: 2rem 2rem 1.5rem;
            margin-bottom: 1.5rem; color: #fff;
        }}
        .page-hero h1 {{ font-size: 1.8rem; font-weight: 800; margin-bottom: .3rem; }}
        .page-hero p {{ opacity: .88; font-size: .95rem; }}
        .page-hero a {{ color: #fff; text-decoration: underline; }}
        .meta-bar {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }}
        .meta-card {{
            flex: 1; min-width: 160px;
            background: #fff; border-radius: 12px;
            padding: 1rem 1.2rem;
            box-shadow: 0 2px 8px rgba(0,0,0,.07);
            border-top: 4px solid var(--accent, #ff6b35);
        }}
        .meta-card:nth-child(1) {{ --accent: #ff6b35; }}
        .meta-card:nth-child(2) {{ --accent: #f7931e; }}
        .meta-card:nth-child(3) {{ --accent: #4ade80; }}
        .meta-label {{
            font-size: .7rem; color: #94a3b8;
            text-transform: uppercase; letter-spacing: .07em; margin-bottom: .25rem;
        }}
        .meta-value {{ font-size: 1rem; font-weight: 700; color: #1e293b; }}
        .highlight-recent {{ color: #16a34a; }}
        .section-card {{
            background: #fff; border-radius: 12px;
            padding: 1.5rem; margin-bottom: 1.25rem;
            box-shadow: 0 2px 8px rgba(0,0,0,.07);
        }}
        .section-card h2 {{
            font-size: .8rem; font-weight: 700; text-transform: uppercase;
            letter-spacing: .08em; color: #ff6b35; margin-bottom: 1rem;
        }}
        .changelog-entry {{
            padding: .65rem 0; border-bottom: 1px solid #f1f5f9;
            display: flex; flex-wrap: wrap; gap: .4rem; align-items: baseline;
        }}
        .changelog-entry:last-child {{ border-bottom: none; }}
        .changelog-date {{
            font-weight: 700; color: #1e293b;
            background: #fff0e6; border-radius: 6px;
            padding: .1rem .5rem; font-size: .85rem;
        }}
        .changelog-msg {{ color: #64748b; font-size: .9rem; }}
        .diff-block {{
            width: 100%; margin-top: .4rem; padding: .6rem .8rem;
            background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;
            font-size: .78rem; white-space: pre-wrap; word-break: break-word;
            color: #475569; font-family: ui-monospace, monospace;
        }}
        .empty-state {{
            text-align: center; padding: 1.5rem;
            color: #94a3b8; font-size: .9rem;
        }}
        .empty-state span {{ font-size: 1.8rem; display: block; margin-bottom: .4rem; }}
        .timeline-content {{
            white-space: pre-wrap; word-break: break-word;
            font-family: ui-monospace, monospace; font-size: .82rem;
            line-height: 1.75; color: #334155;
            background: #f8fafc; border-radius: 8px;
            border: 1px solid #e2e8f0; padding: 1rem 1.2rem;
            max-height: 55vh; overflow-y: auto;
        }}
    </style>
</head>
<body>
    <main style="max-width:860px; margin:0 auto; padding:2rem 1rem;">

        <div class="page-hero">
            <h1>🏃 NYRR Registration Timeline</h1>
            <p>Watches <a href="{TIMELINE_URL}" target="_blank">nyrr.org/race-registration-launch-timeline</a> for new batch release dates. Scans 4× daily via GitHub Actions.</p>
        </div>

        <div class="meta-bar">
            <div class="meta-card">
                <div class="meta-label">Last Checked</div>
                <div class="meta-value">{now_str}</div>
            </div>
            <div class="meta-card">
                <div class="meta-label">Last Changed</div>
                <div class="meta-value {highlight_class}">{changed_label}{"  ← recent" if changed_age_days <= 7 else ""}</div>
            </div>
            <div class="meta-card">
                <div class="meta-label">Changes Detected</div>
                <div class="meta-value">{len(changelog)}</div>
            </div>
        </div>

        <!-- nyrr-commentary-here -->

        <!-- nyrr-reddit-here -->

        <div class="section-card">
            <h2>Changelog</h2>
            {changelog_section}
        </div>

        <div class="section-card">
            <h2>Current Content</h2>
            <div class="timeline-content">{content_html}</div>
        </div>

    </main>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    print(f"[nyrr_watcher] {now_str} — fetching timeline...")

    try:
        content = fetch_timeline()
    except RuntimeError as exc:
        print(f"[nyrr_watcher] WARN: {exc}", file=sys.stderr)
        # Render page with last-known state so timestamp still updates
        state = load_state()
        html = render_html(state, now_str + " (fetch failed — queue active)")
        if not args.dry_run:
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT_FILE.write_text(html)
        sys.exit(0)

    state = load_state()
    new_hash = sha256(content)
    changed = new_hash != state["hash"]

    if changed and state["hash"]:
        diff_summary = compute_diff_summary(state["content"], content)
        print(f"[nyrr_watcher] Content changed!\n{diff_summary}")
        state["changelog"].append(
            {
                "date": now.strftime("%Y-%m-%d"),
                "summary": "Timeline page updated",
                "diff": diff_summary,
            }
        )
        state["last_changed"] = now.isoformat()
    elif not state["hash"]:
        print("[nyrr_watcher] First run — baseline established.")
        state["last_changed"] = now.isoformat()
    else:
        print("[nyrr_watcher] No change detected.")

    state["hash"] = new_hash
    state["content"] = content

    html = render_html(state, now_str)

    if not args.dry_run:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(html)
        save_state(state, dry_run=False)
        print(f"[nyrr_watcher] Written → {OUTPUT_FILE}")
    else:
        print("[nyrr_watcher] Dry-run: no files written.")
        print(f"  Content preview: {content[:300]!r}")


if __name__ == "__main__":
    main()
