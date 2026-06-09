---
description: Classify images in a folder (GoogleScreenAI → CLIP fallback) — outputs is_chart / country / economic_topic CSV
---

Classify all images in the folder specified by `$ARGUMENTS`.

## Steps

1. Extract folder path from `$ARGUMENTS`. If missing or empty, ask: "Which folder should I classify? (provide the full path)"
2. Run:
```bash
python3 /Users/macproajb/claude_projects/classify_screenshots/classify_screenshots.py --folder "<FOLDER>"
```
3. Report: backend used (ScreenAI or CLIP), images found, images processed, CSV output path.

## Parameters
| Flag | Default | Description |
|------|---------|-------------|
| `--folder` | required | Directory containing images to classify |
| `--out` | `<folder>/screenshot_index.csv` | Custom CSV output path |
| `--dry-run` | off | Print rows without writing CSV |

## Notes
- Supports `.png`, `.jpg`, `.jpeg`, `.webp`
- Skips already-processed images (appends to existing CSV)
- Primary backend: `google/screen-ai-v1` via HF InferenceClient (requires `HF_TOKEN` + gated access)
- Fallback: `openai/clip-vit-large-patch14` local zero-shot (no token needed; ~60s first-run load)
- CSV fields: `filename, filepath, is_chart, country, economic_topic`
