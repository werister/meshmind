"""Offline panel scoring on hard-10 votes (9 models). Majority, ties abstain."""
import itertools
import json

FAM = {"falcon3:3b": "falcon", "nemotron-3-nano:4b": "nemotron",
       "granite3.1-moe:3b": "granite", "voter-granite-moe:3b": "granite",
       "gemma3:1b-it-q4_K_M": "gemma", "phi4-mini:latest": "phi",
       "huggingfacetb-smollm3-3b-q4-k-m:bakeoff": "smollm",
       "granite3.3:2b": "granite", "qwen2.5-coder:1.5b": "qwen"}
EXP = ["yes", "no", "yes", "no", "no", "yes", "yes", "yes", "no", "yes"]
votes = {}
for line in open("/tmp/lab_bench11_hardval.jsonl"):
    r = json.loads(line)
    votes.setdefault(r["model"], {})[r["item"]] = r["vote"]
# earlier hard-10 runs live in bench5-era transcript? No: hard votes for the
# first 4 came from lab_bench8 (transcript has them)
for line in open("/tmp/lab_bench8_transcript.jsonl"):
    r = json.loads(line)
    votes.setdefault(r["model"], {})[r["item"]] = r["vote"]
print("models:", sorted(votes), len(votes))


def score(members):
    s = 0
    for i in range(10):
        ys = sum(1 for m in members if votes[m][i] == "yes")
        ns = sum(1 for m in members if votes[m][i] == "no")
        if ys == ns:
            continue
        s += ((ys > ns) and EXP[i] == "yes") or ((ns > ys) and EXP[i] == "no")
    return s


res = []
ms = sorted(votes)
for k in (2, 3):
    for combo in itertools.combinations(ms, k):
        fams = {FAM[m] for m in combo}
        res.append((score(combo), len(fams) == k, k, combo))
res.sort(key=lambda r: (-r[0], r[2]))
print("== top 10 hard panels ==")
for s, mixed, k, combo in res[:10]:
    print(f"{s}/10 k={k} {'mixed' if mixed else 'SAMEFAM'} {list(combo)}")
singles = {m: score([m]) for m in ms}
print("singles:", dict(sorted(singles.items(), key=lambda x: -x[1])))
print("best mixed:", max(s for s, m, _, _ in res if m),
      "best samefam:", max(s for s, m, _, _ in res if not m))
