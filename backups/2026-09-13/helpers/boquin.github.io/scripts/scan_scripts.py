"""
scan_scripts.py — scan filesystem for .py/.ipynb files, evaluate each with Gemma 4,
output a CSV table: filename, location, description, tags, quality score.

Usage:
    export HF_TOKEN=hf_...
    python scan_scripts.py --dirs ~/claude_projects ~/boquin.github.io --max-files 100
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

from huggingface_hub import InferenceClient

MODEL_ID = "google/gemma-4-31B-it"
MAX_CHARS = 6000
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "site-packages", ".tox", "dist", "build", ".eggs", ".mypy_cache",
    ".pytest_cache", ".ruff_cache",
}


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_scripts(roots: list[Path], max_files: int) -> list[Path]:
    found = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if fname.endswith((".py", ".ipynb")):
                    found.append(Path(dirpath) / fname)
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
        cells = nb.get("cells", [])
        parts = []
        for cell in cells:
            if cell.get("cell_type") == "code":
                src = cell.get("source", [])
                if isinstance(src, list):
                    parts.append("".join(src))
                else:
                    parts.append(src)
        return "\n\n".join(parts)[:MAX_CHARS]
    except Exception as e:
        return f"# read error: {e}"


def extract_code(path: Path) -> str:
    if path.suffix == ".ipynb":
        return read_ipynb(path)
    return read_py(path)


# ---------------------------------------------------------------------------
# Gemma call (pattern from injecting_gemma_commentary.md)
# ---------------------------------------------------------------------------

def call_gemma(code: str, filename: str, client: InferenceClient) -> dict:
    prompt = f"""[ROLE]: Expert Python code reviewer.
[TASK]: Analyze the script below and return ONLY a JSON object — no explanation, no markdown fences.
[FORMAT]: Exactly this shape:
{{"description": "1-2 sentence summary of what this script does", "tags": ["tag1", "tag2", "tag3"], "score": 7}}
Tags should be concise lowercase strings (e.g. data-analysis, web-scraping, visualization, api, automation, finance, ml, nlp, utility, etl, plotting, cli).
Score is an integer 1-10 based on code clarity, structure, error handling, and documentation.
[DATA] filename={filename}:
{code}"""

    messages = [{"role": "user", "content": prompt}]

    for attempt in range(5):
        try:
            stream = client.chat.completions.create(
                messages=messages,
                temperature=0.2,
                max_tokens=512,
                stream=True,
            )
            parts = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    parts.append(delta)
                    print(delta, end="", flush=True)
            print()
            raw = "".join(parts).strip()
            # strip markdown fences if model adds them anyway
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"description": "parse_error", "tags": [], "score": 0}
        except Exception as e:
            is_rate_limit = any(
                x in str(e) for x in ("429", "503", "Too Many Requests", "Service Temporarily Unavailable")
            )
            if is_rate_limit and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"\n[rate limit] waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                print(f"\n[error] {e}")
                return {"description": f"error: {e}", "tags": [], "score": 0}

    return {"description": "max_retries_exceeded", "tags": [], "score": 0}


# ---------------------------------------------------------------------------
# CSV writer (incremental)
# ---------------------------------------------------------------------------

COLUMNS = ["filename", "location", "description", "tags", "score"]


def open_csv(output: Path):
    is_new = not output.exists() or output.stat().st_size == 0
    fh = open(output, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=COLUMNS)
    if is_new:
        writer.writeheader()
    return fh, writer


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scan scripts and evaluate with Gemma 4")
    parser.add_argument("--dirs", nargs="+", default=[str(Path.home())], help="Root dirs to scan")
    parser.add_argument("--output", default=str(Path.home() / "script_inventory.csv"), help="Output CSV path")
    parser.add_argument("--max-files", type=int, default=500, help="Max files to process")
    args = parser.parse_args()

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("Error: HF_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    roots = [Path(d).expanduser().resolve() for d in args.dirs]
    output = Path(args.output).expanduser()

    print(f"Scanning: {[str(r) for r in roots]}")
    scripts = find_scripts(roots, args.max_files)
    print(f"Found {len(scripts)} scripts\n")

    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    fh, writer = open_csv(output)

    try:
        for i, path in enumerate(scripts, 1):
            print(f"[{i}/{len(scripts)}] {path}")
            code = extract_code(path)
            result = call_gemma(code, path.name, client)
            writer.writerow({
                "filename": path.name,
                "location": str(path),
                "description": result.get("description", ""),
                "tags": ", ".join(result.get("tags", [])),
                "score": result.get("score", 0),
            })
            fh.flush()
            if i < len(scripts):
                time.sleep(2)
    finally:
        fh.close()

    print(f"\nDone. Results saved to: {output}")


if __name__ == "__main__":
    main()
