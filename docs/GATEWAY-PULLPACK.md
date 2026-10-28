# Gateway pull-pack — 5-slot bake-off roster (T9)

Freshness re-checked **2026-10-28** against the **Ollama registry**
(`registry.ollama.ai/v2/library/.../manifests/<tag>` for exact bytes,
`ollama.com/library/<model>/tags` for the tag set) and the **Hugging Face
API** (`huggingface.co/api/models/<repo>?blobs=true` for exact GGUF
filenames + bytes). Builder pane had full network; both registries returned
HTTP 200. **Blog/benchmark claims are leads; the registry tag / HF blob size
is the evidence.** Every size below is a measured byte count from the
manifest/blob, converted to GB (÷1e9) for the expect band.

The coordinator re-verifies each line against the registry/HF **before the
first pull** (ticket acceptance). No pull without a verified line here.
mini_pull.py asserts post-pull size within ±20% of `expect_gb`.

## Decision summary (per slot)

| Slot | Decision | Resolved spec | Expect GB | Evidence |
|---|---|---|---|---|
| Granite micro hybrid | **KEEP** (newest same-class hybrid w/ registry tag) | `tag:granite4:micro-h` | 1.943 | manifest 1,942,583,381 B |
| LFM2 1.2B | **SUPERSEDE → LFM2.5** (newer official drop-in, same class) | `gguf:…/LFM2.5-1.2B-Instruct-Q4_K_M.gguf` | 0.731 | HF blob 730,895,168 B, lastModified 2026-09-22 |
| SmolLM3 | **KEEP, RESOLVED** (was unresolved; now exact GGUF) | `gguf:…/HuggingFaceTB_SmolLM3-3B-Q4_K_M.gguf` | 1.915 | HF blob 1,915,305,792 B |
| Gemma 3 4B | **KEEP** (no dense-4B same-class tag in newer gemma4) | `tag:gemma3:4b` | 3.350 | manifest 3,350,272,403 B |
| Qwen3 1.7B | **KEEP** (no `qwen3.5:1.7b`; nearest newer is 2B, different class + heavier) | `tag:qwen3:1.7b` | 1.359 | manifest 1,359,293,444 B |

## Pull-pack lines (coordinator consumes these verbatim)

Spec grammar (contracts v1.2 `mini_pull.py --spec`): `tag:NAME` **or**
`gguf:URL|FILE`. `URL` is the HF `resolve/main/<file>` download URL; `FILE`
is the local filename `ollama create` will reference in its Modelfile. For a
`gguf:` line, `mini_pull.py` **downloads `URL` → `<gguf_dir>/<FILE>` (chunked
stream, redirects followed) before** writing `FROM ./<FILE>` and running
`ollama create` — the coordinator does not pre-fetch the weights by hand.

### 1. Granite micro hybrid — `granite4:micro-h`  [KEEP]
- spec: `tag:granite4:micro-h`
- expect_gb: `1.943`  (band 1.554–2.332)
- source: `https://ollama.com/library/granite4:micro-h`
- verify (coordinator, pre-pull):
  ```
  curl -s https://registry.ollama.ai/v2/library/granite4/manifests/micro-h \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print(sum(l["size"] for l in d["layers"])+d["config"]["size"])'
  # expect 1942583381
  ```
- pull: `python3 scripts/mini_pull.py pull --spec tag:granite4:micro-h --expect-gb 1.943`

### 2. LFM2.5 1.2B Instruct — GGUF  [SUPERSEDES LFM2-1.2B]
- spec: `gguf:https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF/resolve/main/LFM2.5-1.2B-Instruct-Q4_K_M.gguf|LFM2.5-1.2B-Instruct-Q4_K_M.gguf`
- expect_gb: `0.731`  (band 0.585–0.877)
- source: `https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF`
- Modelfile note: `FROM ./LFM2.5-1.2B-Instruct-Q4_K_M.gguf` (ollama create
  `lfm2.5-1.2b:bakeoff`); coordinator names the tag at create time.
- verify (coordinator, pre-pull):
  ```
  curl -s 'https://huggingface.co/api/models/LiquidAI/LFM2.5-1.2B-Instruct-GGUF?blobs=true' \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print(next(s["size"] for s in d["siblings"] if s["rfilename"]=="LFM2.5-1.2B-Instruct-Q4_K_M.gguf"))'
  # expect 730895168
  ```
- pull: `python3 scripts/mini_pull.py pull --spec 'gguf:https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF/resolve/main/LFM2.5-1.2B-Instruct-Q4_K_M.gguf|LFM2.5-1.2B-Instruct-Q4_K_M.gguf' --expect-gb 0.731`
- why superseded: MODEL-FIT listed the LFM2-1.2B generation. LFM2.5-1.2B-Instruct
  is the newer official LiquidAI drop-in **in the same 1.2B size class**
  (Q4_K_M 730,895,168 B ≈ byte-for-byte the LFM2-1.2B Q4_K_M footprint of
  730,893,248 B — no envelope cost), lastModified 2026-09-22. LFM3-1.7B also
  shipped but is a **larger (1.7B) class** → not a same-class drop-in, left as
  a Tier-2 lead.

### 3. SmolLM3 3B — GGUF  [RESOLVED — was the open unknown]
- spec: `gguf:https://huggingface.co/bartowski/HuggingFaceTB_SmolLM3-3B-GGUF/resolve/main/HuggingFaceTB_SmolLM3-3B-Q4_K_M.gguf|HuggingFaceTB_SmolLM3-3B-Q4_K_M.gguf`
- expect_gb: `1.915`  (band 1.532–2.298)
- source: `https://huggingface.co/bartowski/HuggingFaceTB_SmolLM3-3B-GGUF`
- Modelfile note: `FROM ./HuggingFaceTB_SmolLM3-3B-Q4_K_M.gguf` (ollama create
  `smollm3:bakeoff`).
- verify (coordinator, pre-pull):
  ```
  curl -s 'https://huggingface.co/api/models/bartowski/HuggingFaceTB_SmolLM3-3B-GGUF?blobs=true' \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print(next(s["size"] for s in d["siblings"] if s["rfilename"]=="HuggingFaceTB_SmolLM3-3B-Q4_K_M.gguf"))'
  # expect 1915305792
  ```
- pull: `python3 scripts/mini_pull.py pull --spec 'gguf:https://huggingface.co/bartowski/HuggingFaceTB_SmolLM3-3B-GGUF/resolve/main/HuggingFaceTB_SmolLM3-3B-Q4_K_M.gguf|HuggingFaceTB_SmolLM3-3B-Q4_K_M.gguf' --expect-gb 1.915`
- resolution note: SmolLM3 has **no Ollama library tag** (checked: empty tag
  set). The authoritative model is `HuggingFaceTB/SmolLM3-3B`; the trusted GGUF
  conversion is bartowski's (official HF repo ships no GGUF). Q4_K_M blob
  1,915,305,792 B; the `resolve/main` URL returned HTTP 206 on a range probe
  (downloadable). **Not DROPPED** — exact filename + bytes are pinned. No
  SmolLM4 / SmolLM3.5 exists (checked HF HuggingFaceTB), so SmolLM3-3B is the
  newest in-class.

### 4. Gemma 3 4B — `gemma3:4b`  [KEEP]
- spec: `tag:gemma3:4b`
- expect_gb: `3.350`  (band 2.680–4.020)
- source: `https://ollama.com/library/gemma3:4b`
- note: size includes the 851 MB vision projector layer — expected, not a
  mismatch. Dense 4B.
- verify (coordinator, pre-pull):
  ```
  curl -s https://registry.ollama.ai/v2/library/gemma3/manifests/4b \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print(sum(l["size"] for l in d["layers"])+d["config"]["size"])'
  # expect 3350272403
  ```
- pull: `python3 scripts/mini_pull.py pull --spec tag:gemma3:4b --expect-gb 3.350`
- why kept over newer: `gemma4` **is** published, but its small tags are
  `e2b` (MatFormer effective-2B, different class; default pull 4.587 GB — over
  the ~3.8–4.4 GB real budget) and then jump to 12B/26B/31B (OOM on 8 GB).
  There is **no dense `gemma4:4b`**. `gemma3n:e2b/e4b` are also MatFormer, not
  a dense-4B same-class drop-in. Gemma 3 4B remains the newest same-class tag.

### 5. Qwen3 1.7B — `qwen3:1.7b`  [KEEP]
- spec: `tag:qwen3:1.7b`
- expect_gb: `1.359`  (band 1.087–1.631)
- source: `https://ollama.com/library/qwen3:1.7b`
- verify (coordinator, pre-pull):
  ```
  curl -s https://registry.ollama.ai/v2/library/qwen3/manifests/1.7b \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print(sum(l["size"] for l in d["layers"])+d["config"]["size"])'
  # expect 1359293444
  ```
- pull: `python3 scripts/mini_pull.py pull --spec tag:qwen3:1.7b --expect-gb 1.359`
- why kept over newer: `qwen3.5` **is** published, but the small tags are
  `qwen3.5:0.8b` (1.322 GB) and `qwen3.5:2b` (2.683 GB). There is **no
  `qwen3.5:1.7b`** — no exact-class drop-in. The nearest newer sibling,
  `qwen3.5:2b`, bumps the size class (1.7B→2B) and nearly doubles the
  footprint (1.359→2.683 GB), eating KV headroom on an 8 GB CPU box. Per the
  same-size-class rule it is **not** a drop-in; recorded here as a Tier-2 lead
  the coordinator may add as a 6th model if budget allows, not as a swap.

## Leads recorded but NOT taken this round (newer, wrong class / unverified-in-class)
- `LiquidAI/LFM3-1.7B-GGUF` — newer gen, but 1.7B class (not 1.2B). Tier-2 lead.
- `ibm-granite/granite-4.2-3b` (HF) — newer Granite point release, but **not**
  published in the Ollama `granite4` library (only 4.0 micro-h / tiny-h tags),
  and 3B is a larger class than micro. Registry has no evidence tag → not taken.
- `qwen3.5:2b` — newer gen, larger class + ~2× footprint. Optional 6th model.
- `gemma4:e2b` / `gemma3n:e2b|e4b` — newer, but MatFormer effective-param arch,
  not a dense-4B same-class replacement; e2b default 4.587 GB is over budget.

## Verdict legend
- **Ran and saw**: registry manifest byte counts, HF blob byte counts, HF
  `resolve/main` 206 range probes (above).
- **Inferred**: envelope-fit reasoning (budget bands) from MODEL-FIT /
  SPARRING §3; the "same-class" judgement for keep-vs-supersede.
- **Not verified**: actual on-Mini pulled size + 1-token probe (coordinator
  executes via mini_pull.py — builder pulls nothing).
