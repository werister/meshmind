"""100-item code bank on the coder shortlist (see docs/T3-bank100-2026-11-13.md)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_bench13_bank as B  # noqa: E402

B.MODELS = [
    "qwen2.5:1.5b",
    "sam860/falcon-h1:1.5b",
    "qwen2.5:3b",
    "qwen2.5-coder:3b",
    "gemma3:1b-it-q4_K_M",
    "nemotron-3-nano:4b",
    "yi-coder:1.5b",
    "granite3.3:2b",
    "nuextract:latest",
    "opencoder:1.5b",
]

if __name__ == "__main__":
    print(f"bank shortlist: {len(B.MODELS)} models", flush=True)
    B.main()
