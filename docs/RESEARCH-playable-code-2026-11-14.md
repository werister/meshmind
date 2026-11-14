# Producing WORKING end-to-end code with small (≤30B) local LLMs

Research date: 2026-11-14. Context: Mac Mini lab, Ollama + Colibri; Flappy Bird benchmark
(complete single-file HTML5 game) fails on small models: broken physics, decorative/static
games, JS crashes. Best snippet model (nemotron-3-nano:4b) wrote incoherent 35-line skeletons.

Ranked by expected leverage for the Flappy benchmark. Every claim cites the primary source
that owns it (paper = arXiv page; harness = source repo/docs; community = original writeup).

---

## 1. Self-repair loop with REAL execution feedback (highest leverage)

Run the artifact, feed back the actual error, repeat 2–5 rounds. Always show the first
real failure (traceback / console error / failing check), not just "it failed".

- Self-Debugging (Chen et al., ICLR 2024): teaches the model rubber-duck debugging via
  few-shot prompts over code + execution results; "can match or outperform baseline
  models that generate more than 10x candidate programs".
  https://arxiv.org/abs/2304.05128
- LDB (Zhong et al.): step-by-step runtime verification; up to +9.8pp across
  HumanEval/MBPP/TransCoder. https://arxiv.org/abs/2402.16906
- VisCoder (small-model numbers): VisCoder-3B/7B gain +19.6/+14.5pp execution pass rate
  over Qwen2.5-Coder, reaching >90% execution pass after ≤3 self-debug rounds.
  https://arxiv.org/abs/2506.03930
- Cross-scale study: +4.9 to +17.1pp HumanEval, +16.0 to +30.0pp MBPP with ≤5 repair
  attempts. https://arxiv.org/pdf/2604.10508
- "Feedback Over Form" (Apr 2026): in 1–3B models, execution feedback is the
  load-bearing mechanism; self-refinement with execution feedback improves codegen by
  >4σ; pipeline topology matters less.
  https://paperz.arrangedbits.com/api/papers/adafada0-0f95-4b9e-8180-2894fc33938b/pdf
- Falsification-not-exposure caveat (Iscan, 2026): on frozen 0.5–1.5B models, repair
  works when feedback falsifies the program, not from mere re-exposure.
  https://arxiv.org/abs/2606.31511v1
- Revision prompts leave ~43% of failing programs unchanged; showing the first failure
  adds ~13pp repair. https://www.mdpi.com/2673-2688/7/9/353
- Community negative result: "improve it" follow-ups on a working game BREAK it
  (multiple setTimeout chains); small models self-correct only on concrete feedback,
  never on open-ended revision.
  https://medium.com/@kristiantolleshaugmrch/i-was-waiting-for-an-rtx-3090-to-run-local-ai-my-old-rtx-2070-changed-my-plans-239b09039748
- For games specifically: AVR-Agent (arXiv 2508.00632) iterates JS games with
  audio-visual recording eval + omni-modal feedback, beating one-shot.
  https://arxiv.org/abs/2508.00632

Flappy mapping: headless-browser harness (page load → console errors → scripted input →
screenshot/pixel checks) feeding console errors + check results back as repair prompts.

## 2. Pin-down prompt: runnable contract + acceptance checklist in the prompt

Include the entry point, controls, required elements, and explicit "must" checks before
asking for code. Tests/specs in the prompt solve problems the model otherwise fails.

- Test-Driven Development for Code Generation (Mathews & Nagappan, ASE 2024): providing
  tests solves +~12.0% MBPP / +~8.5% HumanEval (GPT-4: 82.3%→90.8% HumanEval,
  80.5%→92.5% MBPP). https://arxiv.org/abs/2402.13521
- BODE-GEN: Bayesian prompt optimization for test-driven generation incl.
  CodeLlama-7B and DeepSeek-Coder-33B. https://arxiv.org/html/2512.15076v1
- Qwen2.5-Coder-7B behavioral study: visible tests help substantially on MBPP+ but
  weakly on HumanEval+ (NL-only already 78%) — tests help most where the small model's
  prior is weakest. https://arxiv.org/pdf/2607.26244v1.pdf
- Convergent community pattern: every successful one-shot game prompt constrains
  format — "single self-contained HTML file, no external dependencies, canvas only,
  return only the file content". Eval Arena EXP-001 Tetris one-shot across 8 open
  models (qwen3-coder:30b, qwen2.5-coder:32b/7b, devstral:24b, phi4:14b) used exactly
  this shape with 6 functional + 5 visual checks.
  https://evalarena.aigensa.com/experiments/exp-001/index.html

Flappy mapping: prompt pins canvas size, gravity/flap numbers or ranges, pipe gap/speed,
score rule, game-over/restart, keyboard+click controls, "no external URLs".

## 3. Multi-sample generate-and-rerank (sample K, filter by execution)

Sample K=8–32 diverse completions (temperature ~0.6–0.8), discard everything that
doesn't run, pick among survivors by behavioral checks. Cheap locally; execution does
the heavy lifting.

- AlphaCode (Li et al., Science 2022): ~1M samples/problem → filter on example tests
  (removes ~99%) → cluster by behavior → top-10; top 54.3% of 5,000+ Codeforces
  competitors. https://arxiv.org/abs/2203.07814
- CodeT (Chen et al., 2022): model-GENERATED tests for dual code↔test agreement;
  HumanEval pass@1 to 65.8%, +18.8pp over code-davinci-002 — no human tests needed.
  https://arxiv.org/abs/2207.10397
- Coder-Reviewer reranking (Zhang et al., 2022): P(prompt|code) scoring with NO
  execution, 66.9 normalized on HumanEval with 100 samples — fallback when execution
  is unavailable. https://arxiv.org/abs/2211.16490

Flappy mapping: sample 8–16 Flappy files, keep those with zero console errors +
bird/pipes animate under scripted input, repair only the best 2–3.

## 4. Scaffold-then-fill (plan/skeleton first, code second)

Two passes: (a) short plan or skeleton (function signatures, file outline — no bodies),
(b) full code conditioned on it, ideally per scaffold item. Short per-step generations
are where ≤30B models are strongest.

- Self-Planning (Jiang et al., TOSEM 2024): plan-then-implement beats direct
  generation on HumanEval/MBPP/HumanEval-X. https://arxiv.org/abs/2303.06689
- Skeleton-of-Thought (Ning et al., 2023): up to 2.39× speedup across 11 models.
  https://arxiv.org/abs/2307.15337
- ChainCoder / outline-then-details (Zheng et al., ICML 2023): coarse-to-fine
  synthesis. https://arxiv.org/abs/2305.00909

Flappy mapping: pass 1 emits ~10 named sections (constants, state, input, physics,
pipes, collision, render, loop, UI); pass 2 fills each in order in one file.

## 5. Task decomposition with explicit integration step

Generate pieces independently in small contexts, then a final composition pass that
stitches them and resolves interfaces. Per-piece checks allow regenerating bad pieces
without redoing the whole.

- Least-to-Most (Zhou et al., 2022): decomposition takes SCAN compositional splits
  from near-failure to ≥99%. https://arxiv.org/abs/2205.10625
- Parsel (Zelikman et al., NeurIPS 2023): searches combinations of per-function
  implementations against tests; code at https://github.com/ezelikman/parsel.
  https://arxiv.org/abs/2212.10561

## 6. Put the plan in FILES, not in the model (harness practice)

Strongest single community technique for a 30B local model: numbered build steps with
per-step checks + acceptance checklist in repo docs; prompt explicitly forbids the
model from planning/renaming/redesigning.

- qwen3-coder:30b via Ollama + DeepSeek Harness built a 14-file, 1109-line playable
  Space Invaders: ARCHITECTURE.md with exact files/exports + 17 numbered build steps
  each with a check; PRD pins every number/string/control + browser-console
  acceptance checklist. ~1h, 42 steps, 2M tokens, 22 tok/s on M1 Max.
  Writeup: https://haddley.github.io/posts/deepseekharnessollama/
  Playable result: https://haddley.github.io/invaders-deepseek-harness-ollama/index.html
- Spec → block implementation → adversarial review → deterministic test (4-stage loop
  for Gemma 26B-A4B / Qwen 35B-A3B class instead of one-shotting).
  https://www.learningatlas.us/learning/video/NC2mE7C4s2c

## 7. Scaffold for small-model failure modes (harness practices)

Concrete mechanisms, each from a harness repo's own docs/README:

- SmallCode (Doorman11991/smallcode, built for 8B–35B; README): forgiving multi-format
  tool-call parser (JSON/YAML/XML/Hermes/plain text + auto-repair); 2-stage tool
  routing (category first, then schemas); patch-first editing ("small models can't
  reliably rewrite whole files"); TODO plan re-injected each turn; contracts block
  "I'm done" until assertions pass; quality monitor (empty turns, hallucinated tools,
  repeat loops); thinking budget; trust decay; snapshots + auto-rollback.
  https://github.com/Doorman11991/smallcode
- little-coder: same-model scaffold redesign takes Qwen3.5-9B Q4 from 19% → 46% on
  Aider Polyglot, beating 10× larger models. Write tool REFUSES existing files
  (redirect to Edit — fired on 57% of exercises); 2048-token thinking budget with
  abort+reinject; ~500 tok/turn skill cards; malformed-call repair + loop abort;
  second attempt on test output (+18% of passes).
  https://itayinbarr.substack.com/p/honey-i-shrunk-the-coding-agent
- Goose tool-shim (aaif-goose/goose docs): converts plaintext tool calls into
  structured calls via a separate interpreter model; "Most locally-hosted models …
  will need the shim." Keys: GOOSE_TOOLSHIM, GOOSE_TOOLSHIM_BACKEND,
  GOOSE_TOOLSHIM_OLLAMA_MODEL. Plus tool deferral (GOOSE_TOOL_DEFERRAL=lookup).
  https://github.com/aaif-goose/goose (docs: documentation/docs/guides/tool-shim.md)
- OpenCode (sst/opencode docs): per-model `compatibility` quirks
  (streamUsage/reasoningField/maxTokensField/cacheFormat) + limit.context; Plan agent
  (read-only planner) + per-agent `model` (strong planner, small worker); zero-config
  Ollama discovery. Raise Ollama context (OpenCode wants 64K+, Ollama defaults 4K).
  https://opencode.ai/docs/providers/ and https://opencode.ai/docs/models/
- Qwen Code (QwenLM/qwen-code docs): Ollama via `modelProviders` in
  ~/.qwen/settings.json (openai auth + local baseUrl); pin
  generationConfig.contextWindowSize; fork subagents for parallel decomposition.
  https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/
- Crush (charmbracelet/crush README): `provider add ollama --type ollama --base-url`,
  auto-discovery; LSP context + Agent Skills; mid-session model switching.
  https://github.com/charmbracelet/crush
- Pi (earendil-works/pi docs): Ollama via ~/.pi/agent/models.json (OpenAI-compat) or
  native llama.cpp router; extensible prompt templates; NO built-in subagents/plan
  mode (user's burden). https://github.com/earendil-works/pi
- Tiered escalation: SmallCode AdaptiveModelRouter (0.3/0.6 failure-rate thresholds);
  zap TUI validated frontier-design + local-code split ("scoped single-file tasks
  passed on every model tested" incl. qwen3-coder-30b). https://zap.justpush.cloud/slm

## 8. Shrink the model's job: constrained output + deterministic engine/checker

Where full freedom fails, have the model emit small closed-vocabulary data (JSON) or
patches while fixed code does the rest.

- Outlines (Willard & Louf, 2023): grammar-guided generation, ~100% structurally
  valid output at ~5–10% per-token overhead. https://arxiv.org/abs/2307.09702,
  https://github.com/dottxt-ai/outlines
- llama.cpp GBNF grammars (first-party docs): ships grammars/, --grammar flag,
  json_schema server field. https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md
  (Local-model guide explicitly recommends grammar constraints for Qwen3-Coder 8B:
  "constrain it … keep tasks single-file". https://llmconfigurator.com/en/guides/coding-agents/tool-calling-local-models)
- SCoT structured chain-of-thought: up to +13.79pp Pass@1 over plain CoT on
  HumanEval. https://arxiv.org/abs/2305.06599
- OpenGameBuilder (Hacktoberfest): Gemma 12B local/Ollama makes a playable
  single-file game from one sentence — world = small closed-vocabulary JSON, model
  fills only colors/air/word-mapping; checker returns errors "in words a model can
  act on"; model EDITS drafts, never full rewrites. 2 calls, ~4.3k tokens, <3.5 min.
  https://dev.to/blaiselabs/opengamebuilder-describe-a-game-in-one-sentence-and-generate-it-using-a-local-llm-like-gemma-4-a6k
- Russian community: Qwen3.5-4B community fine-tune writes a Three.js scene from
  text → deterministic GLB exporter, CPU-only laptop via Ollama.
  https://vc.ru/ai/3247982-neyroset-qwen-4b-generiruet-low-poly-assety-dlya-godot-v-formate-glb
- Caveat: grammars guarantee syntax, not semantics — pair with execution (#1/#3).

## 9. Domain-specialized small models + game-specific agentic frameworks

- OpenGame (CUHK MMLab, arXiv 2604.18394): THE closest prior art — open-source
  agentic framework for end-to-end playable web games; Game Skill = Template Skill
  (growing skeleton library) + Debug Skill (living protocol of VERIFIED fixes);
  GameCoder-27B (27B!) via continual pre-training + SFT + execution-grounded RL;
  OpenGame-Bench scores Build Health / Visual Usability / Intent Alignment via
  headless browser + VLM judge; SOTA across 150 game prompts.
  Paper: https://arxiv.org/abs/2604.18394 — Code: https://github.com/leigest519/OpenGame
- SemCoder-6.7B: trained to reason about execution; beats GPT-3.5-turbo on codegen
  (81.1% vs 76.8% HumanEval). https://www.aimodels.fyi/papers/arxiv/semcoder-training-code-language-models-comprehensive-semantics
- CYCLE: 350M–3B models trained to self-refine from test feedback.
  https://www.citedrive.com/en/discovery/cycle-learning-to-self-refine-the-code-generation/
- Model picks with community evidence: qwen3-coder:30b one-shots working Pong/single
  files (https://github.com/norhtecmbarnes-dot/agent-dashboard/blob/HEAD/book/Chapter-5B-Your-First-Program-One-Shot-Game.md,
  https://www.promptinjection.net/p/quick-review-qwen3-coder-ai-llm-in-practice);
  Gemma 4 E4B one-shots playable Tetris on an RTX 2070
  (https://medium.com/@kristiantolleshaugmrch/...); Qwen3.5-Coder strong even at Q2
  quant (https://aihaberleri.org/en/news/qwen35-coder-emerges-as-surprising-powerhouse-at-aggressive-quantization-levels);
  Qwen3.8:27B Snake first try via Ollama
  (http://dev.to/thecodestreet/claude-code-for-free-local-setup-with-ollama-qwen-38-26hp).
- Related benchmark: "The Single-File Test" (arXiv 2605.06707) — 68 single-file HTML
  generations incl. flappy_bird prompt; code verbosity driven by model family, not
  prompt wording. https://arxiv.org/abs/2605.06707

## 10. Role/persona priming (weakest — cheap seasoning only)

One-line system prompt ("You are an expert programmer…") + output constraints.

- Khojah et al. (IEEE TSE 2025): persona has small positive effect on quality but
  slightly LOWER correctness; most prompt techniques had little impact.
  https://arxiv.org/abs/2412.20545
- No published evidence of persona alone moving pass@1 more than ~1–2pp.

## 11. Niche-datapoint roundup (single-source, lower confidence)

- 15-model tower-defense one-shot: local-model failures were GAME LOGIC (enemies
  don't die, negative currency), not syntax — argues for behavioral checks, not just
  console-error checks. https://bentech.substack.com/p/can-your-llm-build-a-tower-defense
  (code: https://github.com/crazydart/llm-testing-tower-defense)
- Higgsfield hackathon winner: text pitch → playable Roblox game on local 27B, one
  RTX 5090. https://www.mlllm.io/articles/3806-comfy-announces-winners-of-open-source-higgsfield-hackathon-with-25-000-prize-pool/
- gemma3:4b via Ollama drove a whole local-first quest game task-by-task in a day
  (human-driven micro-decomposition). https://dev.to/sammysncar/i-drove-an-ai-agent-to-build-a-local-first-outdoor-quest-game-in-a-day-i0d
- Japanese (Qiita/Zenn): mostly setup/speed tuning, no standout one-shot-game
  writeup found. Korean/Chinese searches surfaced the same English articles.
- GAP: direct Bilibili/V2EX/Xiaohongshu/Zhihu searching needs network access —
  agent-reach CLI was unusable from the research sandbox (shell has no outbound
  network; add/check subcommands crash on state writes). Re-run from a networked
  shell: `agent-reach bilibili search …`, `agent-reach v2ex …`, `agent-reach
  xiaohongshu search … --backend public-web`.

---

## RECOMMENDED PROTOCOL: next Flappy attempt ("Flappy-2")

Stack (highest ROI first): pin-down prompt (#2) → scaffold-then-fill (#4) → sample
K=8–16 + execution filter (#3) → ≤5 self-repair rounds on real console output (#1) →
patch-only repairs (#7) → one-line system prompt (#10).

### A. System prompt (one line)
"You are an expert game programmer. Output a single self-contained HTML file and
nothing else — no markdown fences, no explanation, no placeholders, no TODOs."

### B. Generation prompt (pin-down contract + scaffold, pass 1+2 in one call)
```
Build a fully playable Flappy Bird clone in ONE self-contained HTML file.
No external dependencies, no external URLs, no images or fonts from the network.
Canvas 2D only. It must run by opening the file in a browser.

REQUIRED MECHANICS (all must work):
1. Canvas 480x640. Gravity pulls the bird down every frame.
2. Click, Space, or tap flaps the bird upward with fixed impulse.
3. Pipes spawn from the right at a steady rate with a vertical gap; they scroll
   left at constant speed. Pipe gap and speed stay constant.
4. Score +1 when the bird passes a pipe. Show score live during play.
5. Collision with a pipe, the ground, or the ceiling ends the run; show GAME OVER
   with final score and BEST score; press R, click, or tap to restart.
6. Start screen: show title + "click to start". Game states: READY, PLAYING, DEAD.

STRUCTURE your file in exactly these sections, in order:
(a) HTML + canvas + minimal CSS, (b) constants, (c) game state, (d) input handlers,
(e) physics update, (f) pipe spawn/update, (g) collision check, (h) render,
(i) main loop with requestAnimationFrame, (j) UI overlays.
First write the section list as an HTML comment, then implement every section fully.
Every function you reference must be defined. No stubs.

HARD RULES: single file; vanilla JS; requestAnimationFrame loop; no setTimeout game
loops; no markdown; no commentary outside the file.
```

### C. Sampling
- Model: qwen3-coder:30b (or best local coder ≤30B) via Ollama; temperature 0.7;
  K=12 samples; keep files that are syntactically complete (end with </html>).
- Rationale: CodeT/AlphaCode-style execution filtering (#3); 12 samples × ~2k tokens
  is minutes on a Mac Mini.

### D. Automatic grading (execution filter + repair feedback source)
Headless-browser check per sample (all scriptable, e.g. Playwright/Chromium):
1. Page loads with ZERO console errors. (Build Health — cf. OpenGame-Bench)
2. Canvas pixels change between frames without input (bird falls / world scrolls).
3. Scripted flap input changes the bird's vertical trajectory vs no-input control.
4. Pipes move left across frames; score increments after a pipe passes under
   scripted play (or expose a deterministic hook: fixed seed + autopilot query
   param is allowed ONLY for grading, game must also be human-playable).
5. Game-over overlay appears after forced collision; restart input returns to play.
Rank by checks passed; repair only the top 2–3.

### E. Repair loop (≤5 rounds per candidate)
Repair prompt = original contract (short form) + current full file + FIRST observed
failure only (console error text, or which check failed + observed vs expected).
Require output as a UNIFIED DIFF / patch against the previous file (patch-first:
small models regress on full rewrites — SmallCode README, little-coder). Re-grade
after each round; stop at 5/5 checks or 5 rounds. Never ask open-ended "improve it"
(it breaks working games — see #1 negative result).

### F. Selection
Report best-of-K after repair; keep the largest behavior cluster on ties (AlphaCode
clustering intuition). Log all K files + grades for the benchmark record.

### G. Optional escalation (if top candidate still fails)
- Shrink-the-job variant (#8): fixed engine file + model emits only a JSON tuning
  block (gravity, flap impulse, pipe gap/speed/spawn) — tests whether failures are
  logic vs tuning.
- Decomposition variant (#5): generate input/physics/render as separate functions
  with pinned signatures, then a composition pass.
- Model swap: GameCoder-27B weights from OpenGame if Ollama-compatible
  (https://github.com/leigest519/OpenGame).
