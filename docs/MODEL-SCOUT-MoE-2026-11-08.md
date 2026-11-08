# Model scout 2026-11-08 — MoE for the 8 GB Intel box

Question: which mixture-of-experts model can actually run here? All tags
below verified against primary sources (ollama.com/library pages fetched
live, or named origin). Box rules still hold: CPU-only, Ollama 0.32.1,
~4k ctx, Mini disk 18 GB free (Nov 8), MacBook disk FULL (stage nothing big).

## The one paragraph that matters

MoE inference keeps ALL experts resident (RAM ~= TOTAL params) but computes
only the routed few (speed ~= ACTIVE params). So on this box MoE buys
speed-per-quality-point, never fit: a 30B-A3B still needs ~20 GB of RAM.
Anything with "30B", "8x7B" or "26B-A4B" in the name is out. Two options fit.

## Pull candidates (ranked)

### 1. `granite3.1-moe:3b` (2.0 GB) — the MoE experiment
- Source: [ollama.com/library/granite3.1-moe/tags](https://ollama.com/library/granite3.1-moe/tags)
  (3.1M pulls, tags 1 year old, 128K ctx rated, tools badge).
- Why: official tag (no Modelfile/GGUF hassle), 3B total params = 3B RAM,
  IBM-designed for low latency. The interesting fight is IN-family:
  granite3.1-moe:3b (old MoE, fast?) vs installed granite4.2:3b (new dense,
  our only reliable small thinker, but 75-95 s/answer).
- Lane fit: voter challenger; tools fallback (badge says tools — verify,
  badges lie); latency comparison vs granite4.2.
- Risks: LOW arch risk (Granite MoE in llama.cpp since 2024; 1-year-old
  tag all but guarantees 0.32.1 loads it). Quality unknown — 2024-vintage
  3B MoE vs 2026 dense 3-4B is exactly the open question. 128K ctx is
  fantasy here — test at 4k.
- Funded by: nothing — Mini has 18 GB free; 2.0 GB needs no removal.
- Test: load smoke (arch OK?), 10Q voter board, T12-lite tools, tok/s.

### 2. OLMoE-1B-7B-0125-Instruct via community GGUF (~4.1 GB) — stretch only
- Source: no official Ollama tag (library search "moe" verified Nov 8).
  GGUF: mradermacher/OLMoE-1B-7B-0125-i1-GGUF, i1-Q4_K_S 4.1 GB
  ("optimal size/speed/quality" per the repo page). Card:
  [allenai/OLMoE-1B-7B-0125-Instruct](https://huggingface.co/allenai/OLMoE-1B-7B-0125-Instruct)
  (Apache-2.0, 7B total / ~1.3B active, English-focused).
- Why: the only sub-10B-total research MoE with official GGUFs; Ai2 claims
  SOTA-among-tiny on MATH/GSM8K/IFEval (vendor claim, treat as lead).
- Lane fit: none proven; pure curiosity pull AFTER granite-MoE measures out.
- Risks: MEDIUM-HIGH. 4.1 GB weights + KV on the 8 GB box is the largest
  resident load we would have tried (deepseek-r1:8b is do-not-run for a
  reason — swap death). Needs Modelfile import (`FROM ./file.gguf`) over
  flaky SSH. English-only, short-context, Jan-2025 vintage.
- Funded by: needs no removal (18 GB free) but needs a stable SSH window.
- Test: load + resident-mem check FIRST; abort to experiment over if swap
  explodes. Then same 10Q board for a MoE-vs-MoE number.

## Rejected (RAM math)

- `qwen3:30b-a3b` / `qwen3.6:35b-a3b` / nemotron-3.5-lightning / nemotron-cascade-2
  (30-35B total): need 16-24 GB+. Out.
- `mixtral:8x7b` (47B total): out by 5x.
- `deepseek-v3` (671B): out, obviously.
- DeepSeek-V2-Lite (16B total, ~10 GB Q4), Qwen1.5-MoE-A2.7B (~9 GB Q4):
  no official small tag, still over budget. Out.
- JetMoE-8B (8B total): community GGUF only, older and weaker than OLMoE,
  same RAM class. Dominated — skip.
- SSD expert-streaming tricks (llama.cpp `--n-cpu-moe`, Jetson writeups):
  not exposed by Ollama; 10-30 tok/s on GPUs, worse on this CPU. Out.

## Verdict

Pull `granite3.1-moe:3b` next SSH window (2.0 GB, official tag, near-zero
arch risk). It is the cheapest possible MoE-vs-dense datapoint on this box.
OLMoE stays a stretch goal behind it. Everything else in the MoE world is
built for 24 GB+ and is not our fight.
