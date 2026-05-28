import os
import sys
import csv
import json
import time
import base64
import argparse
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
CSV_FIELDS = ["filename", "filepath", "is_chart", "country", "economic_topic"]
MODEL_SCREENAI = "google/screen-ai-v1"
MODEL_CLIP = "openai/clip-vit-large-patch14"

PROMPT = """Analyze this screenshot and respond with ONLY valid JSON, no markdown, no explanation:
{
  "is_chart": "yes or no",
  "country": "country or region name, or empty string if not a chart or unclear",
  "economic_topic": "one of: GDP, Inflation, Trade, Employment, Debt, Interest Rates, FX, PMI, Housing, Equities, Banking, Other — or empty string if not a chart"
}"""

TOPICS = ["GDP", "Inflation", "Trade", "Employment", "Debt",
          "Interest Rates", "FX", "PMI", "Housing", "Equities", "Banking"]

COUNTRIES = [
    "United States", "China", "European Union", "Japan", "Germany",
    "United Kingdom", "India", "Brazil", "France", "Italy", "Spain",
    "Canada", "Australia", "South Korea", "Mexico", "Russia", "Turkey",
    "Indonesia", "Saudi Arabia", "Argentina", "South Africa", "Nigeria",
    "Poland", "Sweden", "Netherlands",
]


def encode_image(path: Path) -> tuple[str, str]:
    ext = path.suffix.lower()
    mime = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode(), mime


def classify_screenai(client, image_path: Path) -> dict:
    b64, mime = encode_image(image_path)
    for attempt in range(3):
        try:
            response = client.chat_completion(
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": PROMPT},
                    ],
                }],
                max_tokens=80,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            return {"is_chart": "error", "country": "", "economic_topic": ""}
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate" in msg.lower():
                wait = 2 ** attempt
                print(f"  rate limit — waiting {wait}s", flush=True)
                time.sleep(wait)
            else:
                print(f"  error: {e}", flush=True)
                return {"is_chart": "error", "country": "", "economic_topic": ""}
    return {"is_chart": "error", "country": "", "economic_topic": ""}


def classify_clip(pipeline, image_path: Path) -> dict:
    from PIL import Image
    img = Image.open(image_path).convert("RGB")

    chart_result = pipeline(img, candidate_labels=["economic chart or graph", "screenshot without chart"])
    is_chart = "yes" if chart_result[0]["label"] == "economic chart or graph" else "no"

    if is_chart != "yes":
        return {"is_chart": is_chart, "country": "", "economic_topic": ""}

    topic_labels = [f"{t} chart" for t in TOPICS]
    topic_result = pipeline(img, candidate_labels=topic_labels)
    best_topic = topic_result[0]["label"].replace(" chart", "")

    country_result = pipeline(img, candidate_labels=COUNTRIES)
    best_country = country_result[0]["label"] if country_result[0]["score"] > 0.15 else ""

    return {"is_chart": "yes", "country": best_country, "economic_topic": best_topic}


def already_processed(csv_path: Path) -> set:
    if not csv_path.exists():
        return set()
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        return {row["filename"] for row in reader}


def probe_screenai(token: str) -> bool:
    try:
        from huggingface_hub import InferenceClient
        client = InferenceClient(model=MODEL_SCREENAI, token=token, provider="hf-inference")
        # Minimal probe: try a 1x1 white PNG
        tiny = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
        client.chat_completion(
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{tiny}"}},
                {"type": "text", "text": "Say OK"},
            ]}],
            max_tokens=5,
        )
        return True
    except Exception as e:
        msg = str(e).lower()
        return "401" not in msg and "403" not in msg and "not found" not in msg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, help="Directory containing images to classify")
    parser.add_argument("--out", default=None, help="CSV output path (default: <folder>/screenshot_index.csv)")
    parser.add_argument("--dry-run", action="store_true", help="Print rows without writing CSV")
    args = parser.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"ERROR: {folder} is not a directory")
        sys.exit(1)

    csv_path = Path(args.out).expanduser().resolve() if args.out else folder / "screenshot_index.csv"

    images = sorted(f for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTS)
    if not images:
        print(f"No images found in {folder}")
        return

    done = already_processed(csv_path)
    pending = [img for img in images if img.name not in done]
    print(f"{len(images)} images found — {len(done)} already done — {len(pending)} to process")

    if not pending:
        print("Nothing to do.")
        return

    # Model selection
    hf_token = os.environ.get("HF_TOKEN")
    use_clip = True
    client = None
    clip_pipeline = None

    if hf_token:
        print(f"Probing {MODEL_SCREENAI}...", flush=True)
        if probe_screenai(hf_token):
            from huggingface_hub import InferenceClient
            client = InferenceClient(model=MODEL_SCREENAI, token=hf_token, provider="hf-inference")
            use_clip = False
            print(f"Backend: {MODEL_SCREENAI}")
        else:
            print(f"ScreenAI not accessible — falling back to local CLIP")

    if use_clip:
        from transformers import pipeline
        print(f"Loading {MODEL_CLIP} (first run may take ~60s)...", flush=True)
        clip_pipeline = pipeline("zero-shot-image-classification", model=MODEL_CLIP, device="cpu")
        print(f"Backend: {MODEL_CLIP}")

    if args.dry_run:
        print("--- DRY RUN (no CSV writes) ---")

    csv_file = None
    writer = None
    if not args.dry_run:
        csv_file = open(csv_path, "a", newline="")
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        if not done:
            writer.writeheader()

    try:
        for i, img in enumerate(pending, 1):
            print(f"[{i}/{len(pending)}] {img.name} ...", end=" ", flush=True)
            if use_clip:
                result = classify_clip(clip_pipeline, img)
            else:
                result = classify_screenai(client, img)

            row = {
                "filename": img.name,
                "filepath": str(img),
                "is_chart": result.get("is_chart", "error"),
                "country": result.get("country", ""),
                "economic_topic": result.get("economic_topic", ""),
            }
            tag = f"is_chart={row['is_chart']}"
            if row["is_chart"] == "yes":
                tag += f" country={row['country'] or 'unknown'} topic={row['economic_topic'] or 'unknown'}"
            print(tag)

            if args.dry_run:
                print(f"  → {row}")
            else:
                writer.writerow(row)
                csv_file.flush()
    finally:
        if csv_file:
            csv_file.close()

    if not args.dry_run:
        print(f"\nDone. Results saved to {csv_path}")


if __name__ == "__main__":
    main()
