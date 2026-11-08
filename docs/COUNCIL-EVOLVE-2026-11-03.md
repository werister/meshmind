# Council protocol evolution 2026-11-03 (champion/challenger, 3 duels)

Meta-council (gemma3, phi4-mini, 2507-instruct, granite4.2) proposed
self-improvements; its chairman top-3 was REJECTED (rankings 0/4
parseable, #1 pick infeasible: multi-node processing on a single Mini).
Salvaged top-3 from member convergence + measured evidence, duelled below.

## Fixed battery
4 factual, temp 0, metric = chairman-final correctness + S2 parse rate.
Held-in: tungsten-74, H2O-YES. Held-out: Au-trap-NO, Paris-YES.

## D1 brevity caps: champion S1/S2 200/350 vs challenger 100/200 (held-in)
Result: champion (2 correct, 6/6 parsed) vs challenger (2 correct, 6/6 parsed).
TIE on quality; challenger ~40% fewer tokens. All earlier format failures
came from LONG inputs; short stages parse. PROMOTED (cost win, zero loss).

## D2 rotating chair on frozen Karpathy Q0 (tungsten, athena said 92)
gemma3: correct (13s). phi4-mini: correct (24s). granite4.2: EMPTY reply.
PROMOTED phi4-mini as alternate chair; granite EXCLUDED (empty over /v1).

## D3 reflection-before-rank vs champion S2 on frozen S1 (Q0+Q1)
champion 6/6 parsed, challenger 6/6 parsed. NO SIGNAL: frozen inputs were
short, the failure regime (long inputs) untested. NO DECISION; retest only
against long-form S1.

## Promoted protocol (v2)
Karpathy 3-stage over /v1, serial, temp 0; S1 cap 100, S2 cap 200;
chair gemma3 (alternate phi4-mini); skeptic framing retained; negative
control per session; transcripts to /tmp (ephemeral) + duel records here.
