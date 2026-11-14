# Local AI Lab — agent quickstart

Base URL (tailnet only, no key needed; the `api_key` value is ignored, send `"ollama"`):

    https://mac-mini-von-hugo-1.taild73e38.ts.net

## Call it

- List models: `GET /api/tags`
- Loaded right now: `GET /api/ps` (also shows RAM per model and context length)
- Chat: `POST /api/chat` with `{"model":"...","messages":[...],"stream":false}`
- OpenAI-compatible: `POST /v1/chat/completions` (same fields as OpenAI)

Python:

    from openai import OpenAI
    client = OpenAI(base_url="https://mac-mini-von-hugo-1.taild73e38.ts.net/v1", api_key="ollama")
    print(client.chat.completions.create(model="gemma3:4b", messages=[{"role": "user", "content": "hi"}]).choices[0].message.content)

curl:

    curl https://mac-mini-von-hugo-1.taild73e38.ts.net/api/chat -d "{\"model\":\"gemma3:4b\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":false}"

## Routing (measured on this 8 GB Intel box; Nov 13-14 campaign)

- Judgment/votes: `qwen3:8b` (T2 63/66) when quality matters; fast lane
  `granite3.1-moe:3b` (13/18 at ~0.5 s/vote). Cheap all-round: `granite4:micro-h`
  (18/18 voter, 20/26 code). See `docs/T2-tier66-2026-11-13.md`.
- General chat: unrevised this campaign — `gemma3:4b` stays the standing pick.
- Fast: `qwen2.5:0.5b` (about 2 s); step up: `qwen3:1.7b` with `"think": false` (~10-20 s, correct on simple reasoning)
- Code: `nemotron-3-nano:4b` (bank 65/100, T1 4/4) for depth;
  `qwen2.5-coder:3b` (bank 64/100) as the faster alternate. Specialist:
  `yi-coder:1.5b` codes 25/26 but cannot follow one-word formats — code only.
  See `docs/T3-bank100-2026-11-13.md`.
- Embed: `nomic-embed-text:v1.5` (`POST /api/embed`, 768 dims, fastest on CPU)
- Tools: `hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M` with the per-tool JSON schema (11-12/12 on the T12 bench); fallback `phi4-mini` (7/12). Always send `"think": false` to tool models
- Reasoning (opt-in): `nemotron-3-nano:4b` or `qwen3:4b-instruct-2507`
  (both 4/4, no thinking needed). Legacy slow lane: `granite4.2:3b` with
  `"think": true` and `num_predict` >= 900 (~75-95 s per answer).
- Keep context at 4k or below (llmfit: nothing above 4k fits here)
- Do NOT run `qwen2.5:14b` or `deepseek-r1:8b` (too big for 8 GB)
- Removed 2026-11-14 (measured weak, freed ~8 GB — do not request):
  `qwen3:4b-thinking-2507`, `phi3.5:3.8b`, `athena-slm`, `LFM3-1.7B`,
  `granite3.1-moe:1b`, `qwen2.5:3b-instruct-q2_K`, `qwen2.5:3b-instruct-q3_K_M`,
  `functiongemma`

Every request names its model. There is no server-side switching and no restart, ever.

### Thinking policy

Think-off is the default everywhere except the reasoning picks above.
Never send `"think": true` to instruct-only models (`gemma3:4b`, `qwen2.5:*`,
`phi4-mini`, `qwen2.5:0.5b`) — the server hard-errors with
"does not support thinking". Small thinkers that over-think past the output
budget return empty answers, so always pair `"think": true` with a generous
`num_predict` (>= 900). `qwen3:4b-thinking-2507` was removed 2026-11-14: it
ignored think:false, and with think:true answered 2/4 at both 900 and 2048
budgets (same items empty) while burning ~5k tokens — use
`qwen3:4b-instruct-2507` instead.

## Web tools

Models reach the live web through the sidecar (metered into `/calls`):

    curl https://mac-mini-von-hugo-1.taild73e38.ts.net/fetch -H "Content-Type: application/json" -d "{\"op\":\"fetch\",\"url\":\"https://example.com\"}"
    curl https://mac-mini-von-hugo-1.taild73e38.ts.net/fetch -H "Content-Type: application/json" -d "{\"op\":\"search\",\"query\":\"Mixture of Experts\"}"

- `{"op":"fetch","url":...}` returns page text (256 KB cap, SSRF-guarded: no localhost, LAN, tailnet, metadata, or non-80/443 ports)
- `{"op":"search","query":...}` returns up to 5 Wikipedia title/url pairs (keyless; general web search needs a key)
- HTTP 200 means the endpoint ran; check the `ok` field. 30 fetches/min per `X-Agent` (429 over)
- `GET /tools` returns the machine-readable tool catalog (same `{name, description, parameters}` schema format as the tool bench) so harnesses can auto-wire these tools

## Leave feedback

After a run, POST one line so the lab log shows real usage:

    curl https://mac-mini-von-hugo-1.taild73e38.ts.net/feedback -H "Content-Type: application/json" -d "{\"agent\":\"my-agent\",\"model\":\"gemma3:4b\",\"ok\":true,\"note\":\"code review, good, 58s\"}"

Fields: `agent` (your name), `model`, `ok` (true/false), `note` (short).
The 5-minute monitor reports feedback volume plus the latest note into `health.log`.

### Reporting token usage

Every API response carries its own exact counts (`prompt_eval_count`, `eval_count`, plus `_duration` fields in nanoseconds). Add your `eval_count` as `tokens` in your feedback POST and the monitor keeps running totals (`total_probe_tokens` for its own checks, `total_feedback_tokens` for agent-reported usage) in `health.log`. Ollama has no server-side lifetime counter, so reported totals only cover usage that agents report.

### Showcase endpoints

- `GET /status` — live JSON: availability, token totals, loaded models, latest feedback.
- `GET /dashboard` — auto-refreshing HTML page with the token counter. Open it in a browser on any tailnet device.
- `GET /agents.md` — this guide, served straight from the lab so remote agents can read it over HTTPS.
Every feedback POST with a `tokens` count feeds the public counter.
