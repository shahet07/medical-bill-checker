"""Rebuild the embeddings index for the knowledge base after editing any guide.

Uses Gemini embeddings (GEMINI_API_KEY). Writes src/billchecker/knowledge/embeddings.json.
The app falls back to keyword search if the index is missing or out of date.

    .venv/bin/python scripts/build_rag_index.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from billchecker.rag import INDEX_FILE, GeminiEmbedder, build_index, load_passages  # noqa: E402

if __name__ == "__main__":
    passages = load_passages()
    index = build_index(passages, GeminiEmbedder())
    INDEX_FILE.write_text(json.dumps(index, separators=(",", ":")))
    print("Indexed {} passages -> {} ({} KB)".format(len(passages), INDEX_FILE, INDEX_FILE.stat().st_size // 1024))
