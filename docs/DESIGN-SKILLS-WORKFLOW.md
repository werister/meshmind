# How Hugo works with design skills (dashboard round 4)

How the round-4 lab dashboard went from a text-heavy status page to the
approved mockup (`mockups/dashboard-round4b.html`), and what made the skills
produce good work instead of a generic template.

## The loop

1. **Brief with hard bars.** Every round started from fixed constraints:
   Apple-light, zero JS, no external assets, measured and self-reported numbers
   never summed, tabular numerals, text with every status colour, visible focus,
   dark mode, reduced motion. The bars decided which skill advice to keep.
2. **Mockup before code.** Hugo stopped the build and asked for a local HTML
   mockup first. No production code (`feedback-server.py`, tests) changed until
   the look was approved.
3. **Show, don't describe.** Reference screenshots (OpenRouter market share and
   activity, Grafana panels, a token-monitor widget, a usage dashboard) set the
   target far better than words. They moved the page from tables and sentences
   to diagram panels with provider logos.
4. **One clear note per round.** "Too much text" led to the diagram panels.
   "Make the fonts consistent" led to one typeface and a six-step scale. Each
   note was specific enough to act on fully.
5. **Approve, then ship.** The mockup was approved before any build or PR.

## Skills used, and the job each one did

| Skill | What it contributed | What was rejected, and why |
|---|---|---|
| ui-ux-pro-max (local) | Accessibility floor: 4.5:1 contrast, 44 px targets, focus rings, no colour-only meaning, reduced motion | Its suggested design system (glassmorphism, Google Fonts, dark navy): breaks Apple-light and no-external-assets |
| apple-design (dickwu) | Design principles, semantic colours, light and dark both first-class, increased-contrast support | None; only SKILL.md was read, not the HIG reference pages |
| taste-skill (Leonxlnx), app-screens | Colour on data not chrome, KPIs as type in one divided strip, lead figure ≤ 40 px, honest zero/dash states, no sparklines on KPIs, ≤ 4 hues per chart | The 48 px figure cap overrode the old 84 px hero counter (now 40 px) |
| motion-design (LottieFiles) | One easing curve, three durations, a 30 ms stagger wave, primary/secondary/ambient layers (bars grow, rows settle, the live dot breathes) | Everything is CSS only and switches off under reduced motion |
| diagram-design (cathrynlavery) | The agent → proxy → model flow diagram, "accent on 1–2 focal elements", "delete until nothing can go" | Its fonts (Instrument Serif, Geist) load via `<link>`, so they're not used. skillsllm.com is only a listing of the same repo |
| data-analytics-skills (nimrodfisher) | Cost avoided shown as a low/base/high range with stated assumptions, never one bare number; hero → trends → breakdowns → detail order | None |
| design-skills (ihlamury) | Tabular numbers and the 2 px focus-outline rule | The extracted Apple and Vercel tokens (for example #808080 body text, 27 px body) fail contrast |

Provider logos are mono SVGs from lobehub/lobe-icons (MIT), drawn inline.

## What made it work

- **Constraints first, skills second.** The skills often disagreed with each
  other and with the brief. The brief broke every tie, so the result stayed
  coherent instead of averaging seven styles.
- **Each skill had a narrow job.** No skill designed the whole page. Each one
  answered one question (accessibility, motion, the flow diagram, the cost range).
- **Real data, honest labels.** Numbers come from the recorded fixture through
  a generator script (`mockups/build-mockup.py`), not hand-typed HTML. Every
  panel is tagged by source: **Measured**, **Self-declared**, **Estimated** or
  **Sample**. Sample splits are asserted to sum exactly to the real totals.
  That let the page look rich without overstating anything.
- **Checked in a real browser.** Every iteration was screenshotted in headless
  Chrome at 1440 px (light and dark) and 390 px. This caught tiny chart labels,
  colliding flow-diagram labels, a phone overflow and a stretched side panel
  before Hugo saw them.
- **Type as a system, not per element.** The font pass replaced about 30 ad hoc
  sizes with tokens: one face, six sizes (12/13/15/20/26/40), three weights, and
  mono only for code. Chart text is scaled per SVG (`--s` = viewBox width ÷
  rendered width), so axis labels match across panels.

## What to do differently next time

- Start from reference images; the first, text-heavy mockup would have been skipped.
- Decide the type scale in the first mockup, not the third.
- Check that a GitHub remote exists before planning a PR.
