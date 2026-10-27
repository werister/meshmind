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
    print(client.chat.completions.create(model="qwen3:4b", messages=[{"role": "user", "content": "hi"}]).choices[0].message.content)

curl:

    curl https://mac-mini-von-hugo-1.taild73e38.ts.net/api/chat -d "{\"model\":\"qwen3:4b\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":false}"

## Routing (measured on this 8 GB Intel box)

- Default quality: `qwen3:4b` (about 1 min per answer; append `/no_think` or send `"think": false` for short ones)
- Fast: `qwen2.5:0.5b` (about 2 s)
- Code: `qwen2.5-coder:3b`
- Tools: `llama3.2:3b`, `phi4-mini`, `functiongemma`
- Keep context at 4k or below (llmfit: nothing above 4k fits here)
- Do NOT run `qwen2.5:14b` or `deepseek-r1:8b` (too big for 8 GB)

Every request names its model. There is no server-side switching and no restart, ever.

## Leave feedback

After a run, POST one line so the lab log shows real usage:

    curl https://mac-mini-von-hugo-1.taild73e38.ts.net/feedback -H "Content-Type: application/json" -d "{\"agent\":\"my-agent\",\"model\":\"qwen3:4b\",\"ok\":true,\"note\":\"code review, good, 58s\"}"

Fields: `agent` (your name), `model`, `ok` (true/false), `note` (short).
The 5-minute monitor reports feedback volume plus the latest note into `health.log`.

### Reporting token usage

Every API response carries its own exact counts (`prompt_eval_count`, `eval_count`, plus `_duration` fields in nanoseconds). Add your `eval_count` as `tokens` in your feedback POST and the monitor keeps running totals (`total_probe_tokens` for its own checks, `total_feedback_tokens` for agent-reported usage) in `health.log`. Ollama has no server-side lifetime counter, so reported totals only cover usage that agents report.

### Showcase endpoints

- `GET /status` — live JSON: availability, token totals, loaded models, latest feedback.
- `GET /dashboard` — auto-refreshing HTML page with the token counter. Open it in a browser on any tailnet device.
- `GET /agents.md` — this guide, served straight from the lab so remote agents can read it over HTTPS.
Every feedback POST with a `tokens` count feeds the public counter.
