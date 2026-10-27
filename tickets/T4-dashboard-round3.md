# T4 — Dashboard round 3

**Assignee:** Sonnet (kiro CLI). **Needs:** SPEC.md, feedback-server.py.
**No Mini SSH** — build against recorded `/status` fixtures only.

## Goal

Dashboard shows measured-vs-reported honestly plus the live call feed:
heatmap/streaks for activity, `/calls` recent-feed section, metering
headline (measured) kept visually distinct from feedback totals
(self-reported, X-Agent labeled "self-declared").

## Scope

- `/calls` recent-feed section (from ring-backed endpoint).
- Activity heatmap + streaks from probe history.
- Metering cards wired to `metering{}`; zero-JS, Apple-light styling kept.
- Fixture-based render test (no live Ollama needed).

## Pass/fail

- Renders from fixtures with no JS and no external assets.
- Measured vs self-reported numbers never summed into one headline.
- Follows the taste anti-slop bar (no gradients-for-decoration,
  no emoji counters, tabular numerals).

## Guardrails

Own worktree only, merge nothing, tiny writes. Coordinator reviews
and deploys the sidecar update to the Mini.
