# Harness sparring review — steel-and-critique of the 35-repo sweep

Target: `/tmp/coding-harness-sweep.md` (35 repos, Mini-lab verdicts, top-5, gap analysis).
Spot-checks (5 README JSONs, max allowed): `74-smallcode`, `94-atomicchat`,
`81-locallyuncensored`, `97-nobodywho`, `83-surf` in `/tmp/reach6/`. Also read
`/tmp/harness-voices-sub.md` (separately cited source, not a README JSON).
Line refs below are `sweep:<n>` for the sweep, `voices:<n>` for the voices note,
and `<repo> README <n>` for `items[0].text` of the named JSON. No network used.

## 1. The 3 strongest claims (keep these)

1. **SmallCode as the primary harness pick.** Best-evidenced call in the sweep:
   8B–35B target, ≤4B-struggles quote, OpenCode comparison table, and the
   timeout knob naming "slow CPU-only llama.cpp servers" all check out nearly
   verbatim against `74-smallcode.json` (README lines 12–16, 20–27, 149–151).
   The "declared dead" defusal is also correct (badge links to
   `commitmentissues.dev`, README line 3) and honestly hedged with "verify
   before depending on it" (sweep:57–59).
2. **Grammar-constrained tool calling as the #1 reliability lever.**
   NobodyWho's README states it explicitly ("automatically generates structured
   grammars from your function signatures", `97-nobodywho.json` line 25), and
   the pasted benchmark's broken-call/overfit/miscount signal (voices:47–48)
   genuinely supports ranking validity above tok/s.
3. **The ≤4B gap is the keystone honest finding.** "No coding harness targets
   ≤4B… The Mini's actual tier (0.5B–4B CPU) has no purpose-built harness"
   (sweep:376–378) survives all five spot-checks — SmallCode's floor is 8B,
   NobodyWho is an engine not a harness, nothing else in the checked set
   contradicts it. This admission is more valuable than any pick.

## 2. Every hole found

### H1. WRONG — SmallCode license "not stated" (flat error)
- Sweep:54 says "License not stated in fetched text."
- `74-smallcode.json` README ends: line 497 `## License`, line 499 `MIT`.
- Correction: SmallCode is **MIT**. One-word fix.

### H2. WRONG VERDICT — Locally Uncensored "fits Mini (borderline)"
- Sweep:116–117 verdicts "fits Mini (borderline)".
- `81-locallyuncensored.json` README line 42 (Download table, macOS row):
  "macOS 14 or newer, Apple Silicon (Beta) … **Intel Macs are not supported.**"
- The sweep's context (sweep:3) is an Intel Mac Mini lab and never mentions
  Linux on the Mini, so the macOS build is excluded by name. Further, README
  line 222: "LU is a desktop app with a window, so it needs a graphical
  session … There is no `--host` flag" — a headless lab box needs VNC/RDP.
- The RAM half of "borderline" is fairly stated (README line 219: "Chat runs
  a 3B model on 8 GB of system RAM with no GPU at all"), but the OS/GUI half
  kills the verdict as written.
- Correction: re-verdict to **MacBook-only** (Apple Silicon beta, Metal —
  README line 231), or at most "fits only if the Mini runs Linux with a
  desktop (AppImage/.deb/.rpm, README line 41)". Either way it leaves the
  "fits Mini" tally.

### H3. SELF-CONTRADICTION — rpocket counted as "fits" while "unverifiable"
- Sweep:294–295: "cannot judge from a tagline; re-fetch before any decision".
- Sweep:334–335 then counts rpocket inside "fits Mini … — 20".
- Unverifiable ≠ fits. (Corroboration from metadata alone, no 6th read:
  `101-rpocket.json` is 1,360 bytes total per directory listing — the
  thin-fetch claim itself is credible.)
- Correction: tally becomes fits 19 + unverifiable 1 (18 + borderline
  accounting per H2 — see H7).

### H4. DROPPED QUALIFIER — Paperless 4B "proven" on 16 GB, applied to 8 GB
- Sweep:355–356: "qwen3.5:4b Q4_K_M is the proven CPU tier."
- Voices:40: the Paperless box is "Intel i3-8100, **16 GB RAM**, no GPU."
  Voices:38 honestly calls it the "closest analog"; the sweep drops the 16 GB
  qualifier while halving the RAM.
- Correction: "…proven CPU tier **on 16 GB**; 8 GB still unproven in-set."

### H5. GAP OVERSTATED — "No 8 GB model-fit picker" is half-solved in-set (×2)
- Gap (sweep:382–384) claims no model-fit picker; the "for the Ollama path"
  scoping saves it literally, but the section headline is "what **nobody in
  this set** solves", and two in-set counterexamples exist:
  - NobodyWho README line 128: 'Pass `"auto"` to fit one to available memory'
    — an explicit memory-fit picker.
  - Locally Uncensored README line 219: "The model manager marks what fits
    before you download."
- Correction: reword to "no fit-picker **for the Ollama path** — though
  NobodyWho's `auto` mode and LU's model manager show the pattern."

### H6. GAP OVERSTATED — "No CPU-only coding-agent benchmark" conflates harness with numbers
- Gap (sweep:391–393): "No CPU-only coding-agent benchmark. Every measured
  number assumes GPU, 16 GB+, or datacenter cards."
- SmallCode README lines 366–384 ships exactly that harness: `smoke` /
  `polyglot-mini` / `tool-use` suites "against any local model" plus a
  CI-diff tool (`bench/diff.js`, exit-coded improved/regressed/noise).
  It runs wherever SmallCode runs — including CPU-only. What is missing is
  published CPU-only *numbers*, not the benchmark.
- Correction: "no **published CPU-only numbers**; SmallCode ships the harness
  — extend it (rec 5) instead of building from scratch." This also upgrades
  rec 5 (see below).

### H7. TALLY INFLATION — "20 fits" mixes harnesses, clients, docs, and unknowns
- After H2 (LU out) and H3 (rpocket → unknown), "20" is really 18, and even
  that mixes: a doc (awesome-local-llm — honestly labeled, sweep:150), an
  Electron notebook on an inferred endpoint (Surf — see H9), and pure clients.
- Correction: restate as **fits 18 + borderline 0 + unverifiable 1
  (rpocket)**, or keep LU as the 1 borderline with the Linux+desktop qualifier.

### H8. INTERNAL TENSION — Rec 1 vs the ≤4B gap (disclose, don't bury)
- Rec 1 (sweep:345–350): make SmallCode primary, "start with the strongest
  coder ≤8B."
- Gap (sweep:376–378): SmallCode's own floor is 8B; the Mini's actual tier
  (0.5B–4B) "has no purpose-built harness."
- So the #1 pick's README says the Mini's tier "struggle[s] with multi-step
  tool use" (74-smallcode lines 12–16), and an in-set datapoint warns that
  "8 GB is a comfortable floor for models up to ~2 GB" (97-nobodywho lines
  112–113) — an 8B Q4 (~5 GB weights + ctx/KV) on 8 GB is plausible but
  unproven anywhere in the set.
- Correction: keep rec 1 but caveat it — "baseline at **both** 8B Q4 (harness
  floor) and 4B (Mini's proven tier); if 8B swaps, the pick is provisional."

### H9. SOFT — Surf "fits Mini" rests on an inference plus unexamined Electron cost
- The Ollama-compatible endpoint is honestly marked inferred (sweep:133–134;
  README only says "Use Local Language Models", 83-surf lines 94–100, details
  in unfetched `docs/AI_MODELS.md`).
- But the README acknowledgements (line 135) show Surf is an **Electron** app —
  ~0.5–1 GB RAM for the shell alone on an 8 GB box — which the verdict never
  weighs. And a notebook is not a coding harness; it pads the "20".
- Correction: demote to "fits Mini (soft — client-side, endpoint unverified,
  Electron RAM unbudgeted)" or drop from harness tallies.

### H10. MIS-MARKED (in the sweep's favor) — NobodyWho CPU support is stated, not inferred
- Sweep:257–258: "CPU fallback implied by 'GPU where available' — inferred."
- README line 105 is explicit: "**Inference uses the GPU where available and
  CPU where not**", plus lines 109–111 (Linux/Windows "fall back to CPU
  without" a Vulkan driver) and Metal-on-Mac (line 110 — Intel Macs do Metal).
- Correction: drop "(inferred)"; the verdict is *better* supported than
  claimed. Bonus the sweep missed: an experimental OpenAI-compatible local
  server (lines 276–288) — a second Ollama-path-compatible backend for rec 2.

### Checked and CLEARED (not holes)
- SmallCode "alive" inference: recent fetch date (2026-05-18), issue refs
  #52/#53/#57/#67, and the prebuild-install note (lines 124–132) all support
  it; "verify before depending" is the right hedge.
- Atomic Chat verdict: 8GB-for-3B (README line 222), CPU TurboQuant ~4.3×
  (lines 88, 126), Node ≥20 (lines 12, 185), MLX engine (line 128),
  OpenCode/Goose/OpenClaude/Kilo integrations (lines 168–173), no license
  section (verified absent) — every clause checks out. Its speculative
  decoding is Apple-Silicon-only (lines 86–87, 149), consistent with the
  CPU-speculative gap.
- "Atomic's zero-broken-calls" attribution: hedged as "this family"
  (sweep:230–231); Atomic Agent is launchable from Atomic Chat (README
  line 98) — fair.
- Gap items "no ≤4B harness", "no CPU speculative decoding", "no standalone
  repair proxy", "no RAM-budget enforcer" all survive the five spot-checks
  (SmallCode's budget engines are token/context-window scope, lines 237, 251 —
  not RAM/OOM; its repair is in-harness, lines 238, 264, 303–304).
- Arithmetic: 20+7+6+1+1 = 35 ✓; 35 JSONs (70–104) + empty 105 ✓.
- Unsloth / XDA-split / Paperless-serialize citations match voices:31–34,
  voices:21–24, voices:42–44 except for H4's dropped 16 GB.

## 3. Corrected top-5 (differs — one-line reasons)

1. **(KEEP, caveated) SmallCode + Mini Ollama as primary harness** — only
   small-model harness in-set, but baseline at both 8B Q4 and 4B per H8.
2. **(NEW @2) Stand up Atomic Chat as the Mini's serving layer** — sole
   in-set stack with stated 8GB-for-3B + CPU TurboQuant + OpenAI-compat
   server + integrations for OpenCode/Goose/Kilo/OpenClaude; the sweep
   buries its best Mini-proven pick at #25.
3. **(KEEP, strengthened) Grammar-constrain tool calls (NobodyWho pattern)**
   — CPU support is stated not inferred (H10), and its `auto` fit-mode
   softens the picker gap (H5).
4. **(KEEP) One Ollama/OpenAI-compatible endpoint + strict serialization**
   — Paperless pattern stands, with the 16 GB qualifier (H4).
5. **(MODIFIED) Extend SmallCode's shipped benchmark instead of building one**
   — smoke/polyglot-mini/tool-use + CI diff already exist (H6); route
   7B+/big-ctx overflow to MacBook MLX (old rec 4 folds in here).

## 4. Verdict: SHIP-WITH-FIXES

Ship after these 8 fixes (all localized, no re-sweep needed):

1. H1: SmallCode license → MIT (sweep:54).
2. H2: Locally Uncensored → MacBook-only (or Linux+desktop-qualified
   borderline); fix sweep:116–117 and the tally.
3. H3/H7: rpocket → unverifiable, excluded from "fits"; restate tally as
   18 fits + 1 unverifiable (+0/1 borderline per fix 2).
4. H4: add "on 16 GB" to the Paperless 4B claim (sweep:355–356).
5. H5: scope the fit-picker gap to "the Ollama path"; cite NobodyWho `auto`
   + LU model manager as the in-set pattern.
6. H6 + rec 5: "no published CPU-only numbers" (not "no benchmark"); rec 5
   becomes extend-SmallCode-bench.
7. H8: caveat rec 1 with the 8B-floor vs ≤4B-tier tension + dual baseline.
8. H9/H10: soften Surf to "(soft)"; drop NobodyWho's "(inferred)" and note
   its experimental OpenAI-compat server.

Fidelity score: 5/5 verdicts directionally right on the checked set, 1 flat
factual error (H1), 1 wrong verdict (H2), 0 fabricated quotes — every checked
quote traces to a real README line. The gaps section needs the H5/H6
softening, and Atomic Chat is under-ranked, but the core thesis (SmallCode
first, grammar-constrain tools, the ≤4B gap is real) stands.
