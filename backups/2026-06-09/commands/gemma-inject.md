# Gemma Inject — HuggingFace Gemma inference pattern

When invoked, take whatever data or page content the user provides, send it to the Gemma model via HuggingFace Inference API, and return the model's output.

## Core pattern

```python
import os
from huggingface_hub import InferenceClient

client = InferenceClient(token=os.environ["HF_TOKEN"])

response = client.chat.completions.create(
    model="google/gemma-3-27b-it",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": USER_CONTENT},
    ],
    temperature=0.2,
    max_tokens=800,
)

print(response.choices[0].message.content.strip())
```

## Instructions

1. `SYSTEM_PROMPT` — derive from what the user wants Gemma to do with the input.
2. `USER_CONTENT` — the raw data, scraped text, or page content passed by the user.
3. If input is large (>4000 chars), truncate or summarise before sending.
4. Print or return the model output directly — no post-processing unless the user asks.
5. `HF_TOKEN` must be set in the environment. If missing, tell the user to `export HF_TOKEN=...`.

## Rate limit handling

```python
import time

for attempt in range(3):
    try:
        resp = client.chat.completions.create(...)
        break
    except Exception as e:
        if ("429" in str(e) or "too many" in str(e).lower()) and attempt < 2:
            time.sleep(30 * (attempt + 1))
        else:
            raise
```
