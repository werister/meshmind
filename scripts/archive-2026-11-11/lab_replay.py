"""Offline panel search: all pairs+triples over 8-item votes, majority rule."""
import itertools
import json

FAM = {
    "granite3.1-moe:3b": "granite", "voter-granite-moe:3b": "granite",
    "granite3.1-moe:1b": "granite", "granite4.2:3b-q4_K_M": "granite",
    "granite4:1b-h": "granite", "granite4:micro-h": "granite",
    "granite3.3:2b": "granite", "granite-code:3b": "granite",
    "phi4-mini:latest": "phi", "phi3.5:3.8b": "phi",
    "gemma3:4b": "gemma", "gemma3:1b-it-q4_K_M": "gemma",
    "qwen2.5:0.5b": "qwen", "qwen2.5:1.5b": "qwen", "qwen2.5:3b": "qwen",
    "qwen2.5-coder:1.5b": "qwen", "qwen2.5-coder:3b": "qwen",
    "qwen3:0.6b": "qwen", "qwen3:1.7b": "qwen",
    "llama3.2:1b-instruct-q4_K_M": "llama", "llama3.2:3b-instruct-q4_K_M": "llama",
    "openbmb/minicpm5-2b:latest": "minicpm",
    "falcon3:3b": "falcon", "sam860/falcon-h1:1.5b": "falcon",
    "huggingfacetb-smollm3-3b-q4-k-m:bakeoff": "smollm",
    "nemotron-3-nano:4b": "nemotron",
    "yi-coder:1.5b": "yi", "opencoder:1.5b": "opencoder",
    "hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M": "artemis",
}
EXP = ["yes"] * 4 + ["no"] * 4
votes = {}
for path in ["/tmp/lab_bench_transcript.jsonl", "/tmp/lab_bench2_transcript.jsonl",
             "/tmp/lab_bench3_transcript.jsonl", "/tmp/lab_bench6_transcript.jsonl"]:
    try:
        for line in open(path):
            r = json.loads(line)
            if "vote" in r and "item" in r and isinstance(r["item"], int):
                votes.setdefault(r["model"], {})[r["item"]] = r["vote"]
    except FileNotFoundError:
        print("missing", path)
full = {m: v for m, v in votes.items() if len(v) == 8}
print(f"models with full 8 votes: {len(full)}")
score1 = {m: sum(1 for i in range(8) if v[i] == EXP[i]) for m, v in full.items()}
short = [m for m, s in score1.items() if s >= 6]
print(f"shortlist (>=6/8): {len(short)}")


def panel_score(members):
    s = 0
    for i in range(8):
        ys = sum(1 for m in members if full[m][i] == "yes")
        ns = sum(1 for m in members if full[m][i] == "no")
        if ys == ns:
            continue  # tie: abstain, no point
        s += ((ys > ns) and EXP[i] == "yes") or ((ns > ys) and EXP[i] == "no")
    return s


results = []
for k in (2, 3):
    for combo in itertools.combinations(sorted(short), k):
        fams = {FAM.get(m, "?") for m in combo}
        results.append((panel_score(combo), len(fams) == k, k, combo))
results.sort(key=lambda r: (-r[0], r[2]))
print("== top 12 panels ==")
seen = set()
n = 0
for s, mixed, k, combo in results:
    if n >= 12:
        break
    n += 1
    print(f"{s}/8 k={k} {'mixed' if mixed else 'SAMEFAM'} {list(combo)}")
best1 = max(score1.values())
print(f"best single: {best1}/8")
mixed_best = max(s for s, m, _, _ in results if m)
same_best = max(s for s, m, _, _ in results if not m)
print(f"best mixed-family: {mixed_best}/8, best same-family: {same_best}/8")
# family coverage of the single best triple
for s, mixed, k, combo in results:
    if k == 3 and mixed and s == mixed_best:
        print("TOP-MIXED-TRIPLE:", json.dumps(list(combo)))
        break
