# Grammar-constrained tool args — draft for the T12 4-tool catalog (2026-11-01)

**Proposals only. No code changed.** Draft per-tool JSON-schema (and GBNF) grammars for the
fixed catalog, plus a wiring sketch for a **two-arm grammar/no-grammar** comparison inside
`scripts/tool_bench.py`, gated to tool-expected turns so p3 (abstain) and p4 (prose) cannot
regress.

## Why this exists
Re-bench (2026-11-01, fixed parser): three-way tie at **7/12** — all three models score
**p2 exact-args 0/2**. Fence artifact is gone (p1 0→2/2 both Qwens), so p2 is genuine
argument imprecision (wrong value/type/key set), not a wrapper bug. A grammar that pins
**enums, types, and the exact key set** is the lever aimed at p2.

## Hard reality check: what the box can actually enforce
- The lab runs **Ollama 0.32.1**. Ollama's `/api/chat` accepts a **`format` field = a JSON
  Schema object** (structured outputs, Ollama ≥0.5) — it does **not** accept raw GBNF.
- **GBNF is a `llama.cpp` `llama-server` feature** (`--grammar` / `grammar` request field),
  not reachable through Ollama. So on *this* box the usable lever is **`format: <schema>`**;
  GBNF is only relevant if a future arm benches via raw `llama-server`.
- Therefore the primary draft below is **JSON-Schema (Ollama-native)**; the GBNF is provided
  as a second, equivalent artifact for the raw-llama.cpp path only, clearly marked.

## The call shape the harness scores (do not drift from this)
The harness convention (from `_system_prompt()` + `parse_tool_call()` + `args_exact()`) is:

```json
{"tool": "<name>", "args": { ...tool-specific... }}
```

NOT OpenAI `name`/`arguments`. The grammar must therefore pin the **outer `tool`/`args`
envelope** too, and `args_exact()` requires: **exact key set** (no extra/missing keys),
**value equality**, and **strict type** (bool is not an int). Catalog arg shapes
(`tests/fixtures/toolbench/catalog.json`):

| tool | arg | type | required | constraint |
|---|---|---|---|---|
| get_weather | city | string | yes | — |
| get_weather | unit | string | no | enum ["c","f"] |
| calc | expression | string | yes | — |
| file_read | path | string | yes | — |
| file_read | max_bytes | integer | no | integer (not float) |
| send_message | to | string | yes | — |
| send_message | body | string | yes | — |

---

## 1. Per-tool JSON-Schema grammars (Ollama `format` — the usable lever)

Each is the schema for the **whole reply object** when a *specific* tool is expected. Because
`format` pins one object, the per-turn arm must select the schema for the tool the scenario
expects (the harness already knows `expect.tool`). Optional args are allowed but, when
present, constrained; `additionalProperties:false` enforces the exact key set that
`args_exact()` demands.

### get_weather
```json
{
  "type": "object",
  "properties": {
    "tool": {"const": "get_weather"},
    "args": {
      "type": "object",
      "properties": {
        "city": {"type": "string", "minLength": 1},
        "unit": {"type": "string", "enum": ["c", "f"]}
      },
      "required": ["city"],
      "additionalProperties": false
    }
  },
  "required": ["tool", "args"],
  "additionalProperties": false
}
```

### calc
```json
{
  "type": "object",
  "properties": {
    "tool": {"const": "calc"},
    "args": {
      "type": "object",
      "properties": {"expression": {"type": "string", "minLength": 1}},
      "required": ["expression"],
      "additionalProperties": false
    }
  },
  "required": ["tool", "args"],
  "additionalProperties": false
}
```

### file_read
```json
{
  "type": "object",
  "properties": {
    "tool": {"const": "file_read"},
    "args": {
      "type": "object",
      "properties": {
        "path": {"type": "string", "minLength": 1},
        "max_bytes": {"type": "integer"}
      },
      "required": ["path"],
      "additionalProperties": false
    }
  },
  "required": ["tool", "args"],
  "additionalProperties": false
}
```
> Note on `max_bytes`: JSON Schema `"type":"integer"` accepts `10` and rejects `10.5`, but
> `10.0` is a borderline case — some validators treat a zero-fraction float as integer.
> `args_exact()` via `_types_match()` is **strict** (`type(10.0) is float != int`), so a model
> emitting `10.0` would pass the grammar but **fail p2**. To make grammar and scorer agree,
> add `"multipleOf": 1` won't help (still float); the honest fix is to keep the scorer strict
> and accept that `format` guarantees integer *form* — llama.cpp's grammar backend emits bare
> integers for `"type":"integer"`, so in practice `10` not `10.0`. Flag for the live run.

### send_message
```json
{
  "type": "object",
  "properties": {
    "tool": {"const": "send_message"},
    "args": {
      "type": "object",
      "properties": {
        "to": {"type": "string", "minLength": 1},
        "body": {"type": "string", "minLength": 1}
      },
      "required": ["to", "body"],
      "additionalProperties": false
    }
  },
  "required": ["tool", "args"],
  "additionalProperties": false
}
```

**What the schema can and cannot fix for p2:**
- **Fixes by construction:** the exact key set (`additionalProperties:false` + `required`),
  the `unit` enum (`c`/`f` — kills `"celsius"`/`"Fahrenheit"`/`"F"` drift), the `tool` name
  (`const`), and the `max_bytes` integer *type*. These are the structural halves of p2.
- **Cannot fix:** the *semantic value* — the model still has to put `"Tokyo"` in `city` and
  `"f"` (not `"c"`) for a Fahrenheit request, and the right arithmetic string in
  `expression`. A schema forces a valid *slot*, not a correct *fill*. So the enum/type/key
  failures should vanish; any residual p2 miss is genuine value reasoning.

---

## 2. GBNF equivalents (raw `llama-server` arm ONLY — not Ollama)

Provided so a future raw-llama.cpp arm can enforce the same shape. Example for `get_weather`
(the others follow the same template; omit for brevity here, generate per-tool):

```gbnf
root        ::= "{" ws "\"tool\"" ws ":" ws "\"get_weather\"" ws "," ws
                "\"args\"" ws ":" ws wargs ws "}"
wargs       ::= "{" ws "\"city\"" ws ":" ws string ( ws "," ws "\"unit\"" ws ":" ws unit )? ws "}"
unit        ::= "\"c\"" | "\"f\""
string      ::= "\"" ([^"\\] | "\\" .)* "\""
ws          ::= [ \t\n]*
```
> This pins key order and the enum. GBNF cannot express "exactly these keys in any order"
> cleanly (order-free optionality balloons the grammar), which is *why* JSON-Schema (which has
> `additionalProperties:false` + unordered `required`) is the better fit — another reason the
> Ollama `format` path is primary and GBNF is the fallback artifact only.

---

## 3. Wiring sketch — two-arm grammar/no-grammar, gated (sketch, not a patch)

Goal: run each scenario **twice per model** — arm A `no-grammar` (today's behavior), arm B
`grammar` — and attribute any p2 gain to the grammar, not the model. Gate B to
**tool-expected turns only** so abstain/prose turns are untouched.

### 3a. CLI
Add one flag; default preserves today's behavior:
```
--arms no-grammar          # default: exactly today's run
--arms no-grammar,grammar  # run both arms, report side by side
```

### 3b. The gate (the safety-critical bit)
A turn is **grammar-eligible** iff its `expect.kind` is a tool call:
```python
GRAMMAR_KINDS = {"tool_call", "recover"}   # NOT abstain/no_tool/use_result
def grammar_for_turn(expect, catalog_schemas):
    if expect.get("kind") not in GRAMMAR_KINDS:
        return None                         # no format -> free-form, p3/p4 safe
    tool = expect.get("tool")
    return catalog_schemas.get(tool)        # per-tool schema, or None if tool unknown
```
Rationale: p3 (abstain = ask for missing arg) and p4 (no_tool = prose) **must** stay
free-form; forcing a JSON object there would make a prose/clarify answer impossible and
regress those points. `use_result` (p6) is also free-form (it answers from the tool result in
prose) — excluded too. Only `tool_call`/`recover` turns get a schema.

### 3c. The live call (only the `--live` path; canned replies are arm-agnostic)
`ask_ollama()` gains an optional `fmt` param threaded from the gate:
```python
def ask_ollama(ollama_url, model, messages, timeout, fmt=None):
    body = {"model": model, "messages": messages, "stream": False, "think": False}
    if fmt is not None:
        body["format"] = fmt          # Ollama JSON-Schema structured output
    ...
```
`run_scenario()` computes `fmt = grammar_for_turn(turn["expect"], schemas)` when arm=="grammar"
and passes it in; when arm=="no-grammar", `fmt=None`. Scoring (`score_turn`, `args_exact`) is
**unchanged** — both arms are judged by the identical rubric, which is what keeps the
comparison honest.

### 3d. Reporting
Extend the findings block to carry both arms per model:
```json
{"model": "...", "arms": {
   "no-grammar": {"aggregates": {...}, "scenarios": [...]},
   "grammar":    {"aggregates": {...}, "scenarios": [...]}}}
```
Console table prints p2 side by side: `p2  no-grammar 0/2  |  grammar X/2`. The delta on p2
(and the deltas on p3/p4, which must be ~0) are the result.

### 3e. Canned-mode note
The 12 committed scenarios use `canned_reply` (offline). Grammar only affects **`--live`**
generation; in canned mode both arms replay the same canned text, so the suite stays 12/12
green and the two-arm code path is exercised without live calls. Add 1–2 fixtures that assert
the gate returns `None` for abstain/no_tool/use_result and a schema for tool_call/recover, so
the gate itself is regression-locked.

---

## 4. Expected p2 impact (hypothesis, pending live run)

- **Structural p2 failures → fixed:** if the current 0/2 is driven by `unit:"celsius"` vs
  `"f"`, extra keys, `name/arguments` instead of `tool/args`, or `max_bytes` as a string, the
  schema removes all of them → p2 should rise toward **2/2** for each model.
- **Semantic p2 failures → unchanged:** if a model picks `"c"` for a Fahrenheit request or
  fumbles the `expression` string, the schema can't save it → p2 stays low. **This is the
  valuable outcome either way:** the two-arm delta *localizes* p2 failure to format vs
  reasoning. Given the models already emit correct JSON (per the fence finding), I'd weight
  toward **p2 improving materially** — the earlier capture showed correct tool+args, so the
  0/2 is plausibly enum/type/key drift, exactly what the schema pins.
- **Overall:** expect the three-way tie to break only if one model's p2 is reasoning-limited
  while another's was format-limited; if all three were format-limited, they likely rise
  together and stay tied — in which case the **efficiency tiebreak stands (artemis 0.85 GB,
  27.7 tok/s)**.

## 5. Risks / caveats

1. **p3/p4/p6 regression** — the whole reason for the gate. If the gate is wrong (schema
   applied to a non-tool turn), a prose/abstain answer becomes impossible → those points
   crash. Mitigation: the gate + the two new gate-unit fixtures; and the report must show
   p3/p4/p6 deltas ≈ 0 as an acceptance check.
2. **Grammar tests the grammar, not the model** — a schema-forced pass is not proof of model
   tool skill. Mitigation: **always keep the no-grammar arm**; report both; never promote a
   model on grammar-arm numbers alone.
3. **`max_bytes` float edge** (§1 note) — grammar allows integer form; scorer is strict. Low
   risk with llama.cpp's integer emission, but watch the live rows.
4. **Ollama-only** — `format` is the Ollama lever; GBNF needs raw `llama-server`. If the lab
   ever A/Bs runtimes, the GBNF artifacts (§2) are ready, but today only the JSON-Schema arm
   runs on the box.
5. **Latency/behavior shift** — constrained decoding can change tok/s and occasionally
   quality on non-constrained parts of the turn; measure arm B's tok/s too, don't assume it's
   free on CPU.
6. **Schema strictness vs real templates** — `additionalProperties:false` is deliberately
   strict to match `args_exact()`. If a model's template wraps the call (e.g. native
   `<tool_call>` tags around the JSON), Ollama's `format` applies to the generated JSON body;
   confirm on the first live row that the constrained output still parses through the existing
   `parse_tool_call()` (it should — `format` yields a bare JSON object, which the bare-JSON
   path already handles).

## 6. Suggested first live step
Run `--arms no-grammar,grammar` on the two p2 scenarios only (`p2a-args-weather-unit`,
`p2b-args-file-maxbytes`) against artemis first (cheapest/fastest), read the raw constrained
output, confirm p3/p4 untouched, then widen to all 12 × 3 models. Keep every number framed as
pending — this is a harness change aimed at a measurement, not a model verdict.

### Sources / cross-ref
`tests/fixtures/toolbench/catalog.json` (arg shapes), `scripts/tool_bench.py`
(`_system_prompt`, `parse_tool_call`, `args_exact`, `_types_match`, `ask_ollama`,
`run_scenario`), `tests/fixtures/toolbench/scenarios/p2a-args-weather-unit.json` (p2 bar),
`T12-tool-bench.md` + MODEL-FIT (re-bench 7/12 tie). Ollama structured-output `format` =
JSON-Schema (≥0.5); GBNF = llama.cpp `llama-server` only. All impact figures are hypotheses
pending the live two-arm run.
