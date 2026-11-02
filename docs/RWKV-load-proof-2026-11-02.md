# RWKV-7 5-minute load proof (Ollama 0.32.1, Intel Mac, CPU-only)

Research spike, 2026-11-02. Read-only, primary sources only, no box access. Nothing here was run on the Mini.

## Blocker first

The box's Ollama 0.32.1 (released 16 Jul) probably cannot load RWKV-7. Every shoumenchougou GGUF card I read says to install Ollama **0.33.2 or later** (0.33.2 released 27 Aug). Expect "unknown architecture" on 0.32.1. Release pages show no year; I inferred 2026 from surrounding dates.

## 1. GGUF (instruct caveat)

- **Pick:** `shoumenchougou/RWKV7-G1g-1.5B-GGUF`, file `rwkv7-g1g-1.5b-Q5_K_M.gguf`, **1.18 GB**.
- **URL:** https://huggingface.co/shoumenchougou/RWKV7-G1g-1.5B-GGUF/resolve/main/rwkv7-g1g-1.5b-Q5_K_M.gguf
- **Why this one:**
  - Its card has a "conversational" tag and a User/Assistant format, and does not call it base.
  - Sibling cards (G1k, G1l) say: "This is a base language model, not a safety-aligned instruction-tuned assistant."
  - No primary source labels any RWKV-7 GGUF "instruct". RWKV does not ship a base/instruct split for G1.
- **2.9B alternative:** `shoumenchougou/RWKV7-G1k-2.9B-GGUF`, `rwkv7-g1k-2.9b-Q5_K_M.gguf`, 2,233,620,416 bytes (2.08 GiB). Its card says base. No G1g 2.9B exists (collection lists only G1k and G1l at 2.9B).
- **Unverified:** the G1g card's own base/instruct wording (README not readable via the fetch tool); any checksum for the G1g file; the official Ollama library `mollysama/rwkv-7-g1:2.9b` (named on the RWKV wiki as Q8_0/Q6_K) because its ollama.com page returned 404, so no size or template.

## 2. Modelfile

Save as `Modelfile` next to the GGUF.

```
FROM ./rwkv7-g1g-1.5b-Q5_K_M.gguf
PARAMETER num_ctx 4096
PARAMETER temperature 1
PARAMETER top_k 128
PARAMETER top_p 0.5
PARAMETER frequency_penalty 0.5
PARAMETER presence_penalty 0.5
PARAMETER repeat_penalty 1
PARAMETER stop """

User:"""
```

- Sampling values are copied from the G1k/G1l `Modelfile.ollama` descriptions. `num_ctx 4096` is our box limit (the cards use 25,600 / 34,304).
- The cards' Modelfile declares `REQUIRES 0.33.2`; omitted here. Whether 0.32.1 would parse it is unverified.
- The cards say keep the `stop` block on three lines; an escaped `\n\n` stores literal backslashes.
- No `TEMPLATE`: the cards rely on the template embedded in the GGUF (an external one overrides it). But the G1g card's "Chat template" field is blank, so the embedded template may be missing. Fallback (my construction from the card's prompt format, not from a source):

```
TEMPLATE """{{- range .Messages }}{{ if eq .Role "user" }}User: {{ .Content }}

{{ else if eq .Role "assistant" }}Assistant: {{ .Content }}

{{ end }}{{ end }}Assistant:"""
```

- Thinking mode: plain prompt ends at `Assistant:`; thinking format ends `Assistant: <think>` (per cards).

## 3. Ollama + RWKV-7 evidence (all fetched this session)

Of the Ollama issues and PRs, none names a release that added rwkv7.

| Source | What it says |
|---|---|
| [issue #10084](https://github.com/ollama/ollama/issues/10084) | "RWKV7 Support", opened 2 Apr 2025. Collaborator dhiltgen, 3 Jul 2026: "This architecture is supported now." No release or PR named. |
| [issue #9653](https://github.com/ollama/ollama/issues/9653) | "RWKV-G1". dhiltgen, 6 Jul 2026: "now supported". No release or PR named. |
| [issue #1612](https://github.com/ollama/ollama/issues/1612) | dhiltgen, 12 Jul 2026: supported, example `ollama run hf.co/shoumenchougou/RWKV7-G1g-1.5B-GGUF:Q4_K_M`. Same thread: v6 landed via llama.cpp #8980 and ollama #6621. |
| [PR #7313](https://github.com/ollama/ollama/pull/7313) | RWKV patch, never merged; author said an upstream llama.cpp sync made it unnecessary. |
| [v0.32.1](https://github.com/ollama/ollama/releases/tag/v0.32.1) | Released 16 Jul. Notes mention no RWKV and no llama.cpp update. |
| [v0.33.0](https://github.com/ollama/ollama/releases/tag/v0.33.0) | Released 21 Aug. No RWKV mention. |
| [v0.33.2](https://github.com/ollama/ollama/releases/tag/v0.33.2) | Released 27 Aug. No RWKV mention. |
| [G1l-2.9B card](https://huggingface.co/shoumenchougou/RWKV7-G1l-2.9B-GGUF), [G1l-1.5B](https://huggingface.co/shoumenchougou/RWKV7-G1l-1.5B-GGUF), [G1k-2.9B](https://huggingface.co/shoumenchougou/RWKV7-G1k-2.9B-GGUF) | Require Ollama 0.33.2+. G1l-2.9B lists "Unknown rwkv7 architecture" as the old-build error ("update Ollama"). Only Q4_K_M was tested for generation, through Ollama. |
| [RWKV wiki, Ollama](https://wiki.rwkv.com/inference/ollama.html) | Says Ollama supports RWKV-7; no minimum version; warns Q5_K_M/Q4_K_M may degrade output. |

**Conflict:** the issues say "supported" on 3-12 Jul, before 0.32.1 shipped (16 Jul), yet the cards demand 0.33.2. The first version that loads rwkv7 is unknown, somewhere in 0.32.x-0.33.2. Treat 0.33.2 as the safe bound. Latest seen: v0.40.13 (28 Oct 2026).

## 4. Unknown-arch vs success

- **Unknown arch (exact text unverified):** `ollama create` may succeed, then `ollama run` fails with something like `unknown model architecture: 'rwkv7'`, or the card's "Unknown rwkv7 architecture".
- **Success:** `ollama show rwkv7-g1g-proof` reports architecture `rwkv7`; `/api/ps` lists the model; a short chat reply ends cleanly. A `head_count = 0` value in GGUF inspectors is expected (G1l card).

### Three likeliest failure modes

1. **Ollama too old (most likely).** Fix: upgrade to >=0.33.2. Whether newer builds still support this Intel Mac is unverified; check before upgrading, since it is a one-way change on the box.
2. **Missing or blank embedded chat template.** Model rambles, invents `User:` turns, or never stops. Fix: add the fallback `TEMPLATE` above and keep the three-line `stop`.
3. **Loads but slow or times out (speculative).** Q5_K_M (1.18 GB) should fit 8 GB RAM; the risk is slow first token through the Caddy proxy. Fix: test directly on `127.0.0.1:11434` with `keep_alive` and a longer client timeout.

## 5. Command block for the Mini

```bash
set -e
ollama --version
mkdir -p ~/rwkv-proof && cd ~/rwkv-proof
curl -L -C - -o rwkv7-g1g-1.5b-Q5_K_M.gguf \
  https://huggingface.co/shoumenchougou/RWKV7-G1g-1.5B-GGUF/resolve/main/rwkv7-g1g-1.5b-Q5_K_M.gguf
ls -l rwkv7-g1g-1.5b-Q5_K_M.gguf   # expect ~1.18 GB
cat > Modelfile <<'EOF'
FROM ./rwkv7-g1g-1.5b-Q5_K_M.gguf
PARAMETER num_ctx 4096
PARAMETER temperature 1
PARAMETER top_k 128
PARAMETER top_p 0.5
PARAMETER frequency_penalty 0.5
PARAMETER presence_penalty 0.5
PARAMETER repeat_penalty 1
PARAMETER stop """

User:"""
EOF
ollama create rwkv7-g1g-proof -f Modelfile
curl -s -m 300 http://127.0.0.1:11434/api/chat -d '{"model":"rwkv7-g1g-proof","messages":[{"role":"user","content":"Say hello in one short sentence."}],"stream":false,"think":false,"options":{"num_predict":60}}'
echo; curl -s http://127.0.0.1:11434/api/ps
```

`think:false` follows our AGENTS.md rule; whether this model accepts it is unverified. If the server rejects it, drop it.

## Sources

- https://github.com/ollama/ollama/issues/10084
- https://github.com/ollama/ollama/issues/9653
- https://github.com/ollama/ollama/issues/1612
- https://github.com/ollama/ollama/pull/7313
- https://github.com/ollama/ollama/releases/tag/v0.32.1
- https://github.com/ollama/ollama/releases/tag/v0.33.0
- https://github.com/ollama/ollama/releases/tag/v0.33.2
- https://huggingface.co/shoumenchougou/RWKV7-G1g-1.5B-GGUF
- https://huggingface.co/shoumenchougou/RWKV7-G1k-2.9B-GGUF
- https://huggingface.co/shoumenchougou/RWKV7-G1l-2.9B-GGUF
- https://huggingface.co/shoumenchougou/RWKV7-G1l-1.5B-GGUF
- https://huggingface.co/collections/shoumenchougou/rwkv7-gxx-gguf
- https://wiki.rwkv.com/inference/ollama.html
