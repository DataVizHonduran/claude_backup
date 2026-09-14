"""
scan_scripts.py — scan filesystem for .py/.ipynb files, evaluate each with Claude Haiku,
output a CSV table: filename, location, description, tags, quality score.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python scan_scripts.py --dirs ~/claude_projects ~/boquin.github.io --max-files 500
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import anthropic

MODEL_ID = "claude-haiku-4-5-20251001"
MAX_CHARS = 6000
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "site-packages", ".tox", "dist", "build", ".eggs", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".cursor", "crewai", "smolagents", ".claude", "fingpt", ".ipynb_checkpoints",
}

SKIP_PATHS = {
    str(Path.home() / "Library" / "Application Support" / "Claude"),
}


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_scripts(roots: list[Path], max_files: int, already_done: set[str]) -> list[Path]:
    found = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            if any(str(dirpath).startswith(sp) for sp in SKIP_PATHS):
                dirnames.clear()
                continue
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if fname.endswith(".ipynb"):
                    p = Path(dirpath) / fname
                    if str(p) in already_done:
                        continue
                    found.append(p)
                    if len(found) >= max_files:
                        print(f"[warn] hit --max-files cap ({max_files}), stopping scan")
                        return found
    return found


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def read_py(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_CHARS]
    except Exception as e:
        return f"# read error: {e}"


def read_ipynb(path: Path) -> str:
    try:
        nb = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        parts = []
        for cell in nb.get("cells", []):
            if cell.get("cell_type") == "code":
                src = cell.get("source", [])
                parts.append("".join(src) if isinstance(src, list) else src)
        return "\n\n".join(parts)[:MAX_CHARS]
    except Exception as e:
        return f"# read error: {e}"


def extract_code(path: Path) -> str:
    if path.suffix == ".ipynb":
        return read_ipynb(path)
    return read_py(path)


# ---------------------------------------------------------------------------
# Claude Haiku call
# ---------------------------------------------------------------------------

def call_claude(code: str, filename: str, client: anthropic.Anthropic) -> dict:
    prompt = f"""[ROLE]: Expert Python code reviewer.
[TASK]: Analyze the script below and return ONLY a JSON object — no explanation, no markdown fences.
[FORMAT]: Exactly this shape:
{{"description": "1-2 sentence summary of what this script does", "tags": ["tag1", "tag2", "tag3"], "score": 7}}
Tags should be concise lowercase strings (e.g. data-analysis, web-scraping, visualization, api, automation, finance, ml, nlp, utility, etl, plotting, cli).
Score is an integer 1-10 based on code clarity, structure, error handling, and documentation.
[DATA] filename={filename}:
{code}"""

    for attempt in range(5):
        try:
            response = client.messages.create(
                model=MODEL_ID,
                max_tokens=512,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            print(raw)
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"description": "parse_error", "tags": [], "score": 0}
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"\n[rate limit] waiting {wait}s...")
            time.sleep(wait)
        except Exception as e:
            print(f"\n[error] {e}")
            return {"description": f"error: {e}", "tags": [], "score": 0}

    return {"description": "max_retries_exceeded", "tags": [], "score": 0}


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

COLUMNS = ["filename", "location", "description", "tags", "score"]


def load_done(output: Path) -> set[str]:
    if not output.exists() or output.stat().st_size == 0:
        return set()
    with open(output, newline="", encoding="utf-8") as f:
        return {row["location"] for row in csv.DictReader(f) if row.get("location")}


def open_csv(output: Path, is_new: bool):
    fh = open(output, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=COLUMNS)
    if is_new:
        writer.writeheader()
    return fh, writer


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scan scripts and evaluate with Claude Haiku")
    parser.add_argument("--dirs", nargs="+", default=[str(Path.home())], help="Root dirs to scan")
    parser.add_argument("--output", default=str(Path.home() / "script_inventory.csv"), help="Output CSV path")
    parser.add_argument("--max-files", type=int, default=500, help="Max NEW files to process per run")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    output = Path(args.output).expanduser()
    already_done = load_done(output)
    if already_done:
        print(f"[resume] skipping {len(already_done)} already-processed files")

    roots = [Path(d).expanduser().resolve() for d in args.dirs]
    print(f"Scanning: {[str(r) for r in roots]}")
    scripts = find_scripts(roots, args.max_files, already_done)
    print(f"Found {len(scripts)} new scripts to process\n")

    if not scripts:
        print("Nothing to do.")
        return

    client = anthropic.Anthropic(api_key=api_key)
    fh, writer = open_csv(output, is_new=not already_done)

    try:
        for i, path in enumerate(scripts, 1):
            print(f"[{i}/{len(scripts)}] {path}")
            code = extract_code(path)
            result = call_claude(code, path.name, client)
            writer.writerow({
                "filename": path.name,
                "location": str(path),
                "description": result.get("description", ""),
                "tags": ", ".join(result.get("tags", [])),
                "score": result.get("score", 0),
            })
            fh.flush()
            if i < len(scripts):
                time.sleep(0.5)
    finally:
        fh.close()

    print(f"\nDone. Results saved to: {output}")


if __name__ == "__main__":
    main()
