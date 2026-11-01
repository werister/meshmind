# Retro — the tools-lane arc: how the harness was the blocker twice (2026-11-01)

A short narrative retrospective of the T12 tools-lane investigation. The raw per-arm
numbers live in `tickets/T12-tool-bench.md` and `docs/MODEL-FIT.md`; this doc is the
*story and the lesson*, because the lesson is reusable and the numbers alone don't carry it.

## The arc in one line
A model with a credible published benchmark (TurinTech Artemis-0.8B, vendor BFCL 163/258)
scored 4/12 on our tool bench, then 7/12, then 11–12/12 — and **the model never changed.**
The harness did, twice. Both times the instinct "the model is weak" was wrong and
"interrogate the measurement" was right.

## The three acts

**Act 1 — the fence artifact (4/12 → wrong conclusion avoided).**
Artemis scored 4/12; qwen3:4b-instruct-2507 scored an *identical-shaped* 4/12 (0/8 on
tool-call turns, 4/4 on non-tool turns). Raw-output capture showed both emitted **correct
tool JSON with the right tool and args** — just without the ``` code fence the parser's
regex required. The 0/8 was a **parser rule rejecting correct output**, not tool inability.
Fix: accept bare `{"tool","args"}` objects (string-aware balanced-brace scan), *not* the
heavier `format:json` route — which preserved the free-form abstain/prose turns.
Result: p1 went 0→2/2 on both Qwens; the fence artifact was gone.

**Act 2 — the three-way tie at 7/12 (a useful null result).**
With the fence fixed, all three models landed at 7/12, and **everyone failed exact-args p2
0/2.** That was the real signal: p2 was no longer a wrapper bug but either genuine argument
imprecision or a scorer stricter than the models were precise. A bare `--format json` arm
(shape-only constraint, gated to tool turns) left p2 **still 0/2 across the board** — proving
shape-constraint can't fix a wrong *value*, and localizing the failure. p3/p4 stayed
unregressed, proving the turn-gating worked.

**Act 3 — the two-arm schema comparison (the split verified).**
A per-tool JSON-Schema arm (pinning the `unit` enum, `max_bytes` integer type, and exact key
set via `additionalProperties:false`), gated to tool-expected turns, run **alongside** the
no-grammar arm so any gain was attributable to the grammar and not the model:
- **artemis: 12/12, then 11/12 on replication; p2 2/2 both runs.** Its failures were
  ~entirely **structural** (enum/type/key-set) — the schema fixes them by construction. The
  only wobble was the *unconstrained* p3 turn, which the gate deliberately leaves free-form,
  so that is correct behavior, not a schema regression.
- **2507: 8/12, p2 still 0/2 even under the schema.** The decisive negative: a schema that
  pins the valid slot still can't make the model fill it correctly, so 2507's p2 failure is
  **genuine value reasoning** (wrong `unit`, wrong `expression`), not formatting.
- **phi4-mini: 7/12 unchanged** — it already fenced correctly, so there was nothing
  structural for the schema to fix.

The predicted split held exactly: **artemis = format-limited (fixable), 2507 =
reasoning-limited (not fixable by grammar).**

## Why the two-arm design mattered
A single-arm (schema-only) run would have shown **artemis 12/12** and we would not have known
whether the *model* or the *grammar* earned it. The paired no-grammar arm is what let us say
"artemis's capability was real, the harness was hiding it" vs "2507's p2 is a true ceiling."
Attribution — not a higher score — was the deliverable. That is why the no-grammar 7/12 arm
**stays on record as the honest baseline**: the schema passes partly test the grammar, and we
never promote on grammar-arm numbers alone.

## The decision
**ADOPTED: Artemis-0.8B + per-tool JSON-Schema for the tools lane.** It scores 11–12/12 at
**0.85 GB / 27.7 tok/s** — tying-or-beating 4B models on capability at a third of the RAM and
~3× the speed, which is exactly the trade that wins on an 8 GB CPU box where RAM and
throughput are the binding constraints. Constrained decoding isn't a crutch here; it's a
legitimate production tool-lane config, and the gating keeps abstain/prose turns free-form.

## The durable lesson (the point of this doc)
**When a model with a credible published score underperforms our harness, suspect the harness
first.** Here the vendor BFCL 163/258 transferred the entire time — the harness blocked it
twice (fence rule, then exact-args structural strictness), and both times the apparatus, not
the model, was the problem. Corollaries now adopted as lab priors:

1. **Keep vendor numbers as "hypothesis pending our harness," not as noise to discard.** The
   number was true before we could see it; discarding it would have been the wrong call.
2. **Two-arm (constrained/unconstrained) is the default for any constrained-decoding bench** —
   so a score increase can be attributed to model vs apparatus, never conflated.
3. **Gate any output constraint to the turns that need it.** Shape/schema constraint on an
   abstain or prose turn would regress those points; gating to tool-expected turns kept
   p3/p4/p6 free-form and intact.
4. **A null result that *localizes* a failure (p2 0/2 under shape-constraint) is worth as much
   as a pass** — it told us where the real ceiling was before we spent effort on the wrong fix.

## Known ceilings & caveats (for the record)
- **2507 p2 is a characterized ceiling, not a mystery:** don't reach for 2507 on exact-args
  tasks without few-shot or a verifier — a schema won't save it.
- **Temperature is unpinned** in the bench; ±1 variance was seen on the unconstrained p3 turn.
  Pinning sampling would tighten replication (artemis's 12 vs 11 likely lives here).
- **Schema arm is Ollama `format`=JSON-Schema**, verified live on the box's Ollama 0.32.1
  (honored correctly, pure JSON out, enum respected). GBNF remains a raw-`llama-server`-only
  path, drafted but not needed on this box.
- **Box-health note:** heavy multi-model live benching pushed the Mini into ~4 GB swap during
  this work; live benches are minutes-per-arm on CPU and should be run one-model-resident and
  spaced out. Not a result caveat, an operational one.

### Cross-ref
`tickets/T12-tool-bench.md` (raw per-arm log), `docs/MODEL-FIT.md` (adoption row),
`docs/GBNF-tools-draft-2026-11-01.md` (the schema/gating design), `scripts/tool_bench.py`
(parser + `--format`/`--schema` arms + turn gate). All vendor figures remain hypotheses that
*this* harness has now, finally, confirmed.
