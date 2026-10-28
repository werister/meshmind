#!/usr/bin/env python3
"""bakeoff.py — compose run_8q -> run_ladder -> (optional) screen per model.

Implements docs/GATEWAY-CONTRACTS.md v1.2 (FROZEN). This script COMPOSES the
frozen run_8q.py / run_ladder.py CLIs by shelling out to them; it does not
reimplement the 8Q filter or the ladder. Tests stub those two scripts.

CLI (contracts v1.2):
  python3 scripts/bakeoff.py --models T1,T2 [--out DIR] [--ollama URL]
      [--status URL] [--screen-cmd TPL] [--questions PATH]

Order per model: run_8q -> run_ladder -> screen (optional).
  - 8Q pass=false -> skip the ladder for that model (filter first, measure
    survivors), screen also skipped; model appears filtered in findings.
  - A failed model is marked and skipped forward, never fatal.
  - --screen-cmd absent/unrunnable -> screen null + note, no crash.
  - Zero survivors -> exit 0, findings.json "models":[], findings.md
    "no survivors".

Conventions: JSON object to stdout, human reasons to stderr, exit 0 = ran
(pass/fail lives inside the JSON), exit 2 = infrastructure error.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RUN_8Q = SCRIPTS_DIR / "run_8q.py"
RUN_LADDER = SCRIPTS_DIR / "run_ladder.py"

# Allow tests to point at stub 8Q/ladder scripts without touching the real CLIs.
RUN_8Q = Path(os.environ.get("BAKEOFF_RUN_8Q", RUN_8Q))
RUN_LADDER = Path(os.environ.get("BAKEOFF_RUN_LADDER", RUN_LADDER))


def _run_json(cmd, timeout):
    """Run a child CLI, return (parsed_json_or_None, note).

    exit 0 with JSON stdout = ran. Anything else (exit 2, non-JSON, timeout,
    missing file) is surfaced as a note so the caller can mark the model and
    continue instead of crashing.
    """
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "cli_not_found"
    except OSError as exc:
        return None, "exec_error:%s" % exc.__class__.__name__
    if proc.returncode == 2:
        reason = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        return None, "infra_error:%s" % (reason[-1] if reason else "exit2")
    try:
        return json.loads(proc.stdout.decode("utf-8", "replace")), None
    except (ValueError, TypeError):
        return None, "bad_json:exit%s" % proc.returncode


def run_8q(model, ollama, questions, timeout=120):
    cmd = [sys.executable, str(RUN_8Q), "--model", model, "--ollama", ollama]
    if questions:
        cmd += ["--questions", questions]
    data, note = _run_json(cmd, timeout)
    return data, note


def run_ladder(model, ollama, status, step_timeout=600):
    cmd = [
        sys.executable, str(RUN_LADDER),
        "--model", model,
        "--ollama", ollama,
        "--status", status,
    ]
    # ladder can run several steps; allow generous headroom above step-timeout.
    data, note = _run_json(cmd, step_timeout * 4)
    return data, note


def run_screen(model, screen_cmd, timeout=600):
    """Shell out to the mml-stack screen template. Absent/unrunnable -> null."""
    if not screen_cmd:
        return None, "no_screen_cmd"
    try:
        rendered = screen_cmd.format(model=model)
    except (KeyError, IndexError, ValueError):
        return None, "screen_cmd_bad_template"
    try:
        argv = shlex.split(rendered)
    except ValueError:
        return None, "screen_cmd_unparseable"
    if not argv:
        return None, "screen_cmd_empty"
    data, note = _run_json(argv, timeout)
    if data is None:
        return None, "screen_%s" % note
    return data, None


def bake_one(model, args):
    """Run the per-model pipeline. Returns a findings record (never raises)."""
    record = {
        "model": model,
        "status": "ran",
        "passed_8q": None,
        "eightq": None,
        "ladder": None,
        "screen": None,
        "notes": [],
    }

    eightq, note = run_8q(model, args.ollama, args.questions)
    if eightq is None:
        record["status"] = "failed"
        record["notes"].append("8q:%s" % (note or "unknown"))
        return record
    record["eightq"] = eightq
    record["passed_8q"] = bool(eightq.get("pass"))
    if eightq.get("notes"):
        record["notes"].append("8q:%s" % eightq["notes"])

    if not record["passed_8q"]:
        # Filter first, measure survivors: no ladder, no screen.
        record["status"] = "filtered"
        record["notes"].append("filtered_by_8q")
        return record

    ladder, note = run_ladder(model, args.ollama, args.status)
    if ladder is None:
        record["status"] = "failed"
        record["notes"].append("ladder:%s" % (note or "unknown"))
        return record
    record["ladder"] = ladder
    if ladder.get("verdict") is False:
        record["notes"].append("ladder_verdict_false")

    screen, snote = run_screen(model, args.screen_cmd)
    record["screen"] = screen
    if snote:
        record["notes"].append(snote)

    return record


def _fmt_cell(value):
    if value is None:
        return "-"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def _ladder_summary(ladder):
    """Best (max tok_s) ok step's tok_s + mem_kb, for the human table."""
    if not ladder:
        return None, None
    steps = [s for s in ladder.get("steps", []) if s.get("ok")]
    if not steps:
        return None, None
    best = max(steps, key=lambda s: (s.get("tok_s") or 0))
    return best.get("tok_s"), best.get("mem_kb")


def _screen_summary(screen):
    if not screen:
        return None
    # Screen schema is mml-stack's; surface a small set if present.
    for key in ("auc", "kappa", "verdict", "score"):
        if key in screen:
            return "%s=%s" % (key, screen[key])
    return "ran"


def write_findings(records, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    survivors = [r for r in records if r["status"] == "ran" and r.get("passed_8q")]

    findings_json = {
        "tool": "bakeoff",
        "models": records,
        "survivors": [r["model"] for r in survivors],
    }
    (out_dir / "findings.json").write_text(
        json.dumps(findings_json, indent=2, sort_keys=True) + "\n"
    )

    lines = ["# Bake-off findings", ""]
    if not survivors:
        lines.append("no survivors")
        lines.append("")
    lines.append("| model | status | 8Q pass | tok/s | mem_kb | screen | notes |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in records:
        tok_s, mem_kb = _ladder_summary(r.get("ladder"))
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s |"
            % (
                r["model"],
                r["status"],
                _fmt_cell(r.get("passed_8q")),
                _fmt_cell(tok_s),
                _fmt_cell(mem_kb),
                _fmt_cell(_screen_summary(r.get("screen"))),
                "; ".join(r.get("notes") or []) or "-",
            )
        )
    lines.append("")
    (out_dir / "findings.md").write_text("\n".join(lines))
    return findings_json


def parse_args(argv):
    p = argparse.ArgumentParser(description="Gateway bake-off runner (contracts v1.2)")
    p.add_argument("--models", required=True, help="comma-separated model tags")
    p.add_argument("--out", default="bakeoff-out")
    p.add_argument("--ollama", default="http://127.0.0.1:11434")
    p.add_argument("--status", default="http://127.0.0.1:8081/status")
    p.add_argument("--screen-cmd", default=None, dest="screen_cmd")
    p.add_argument("--questions", default=None)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        sys.stderr.write("no models given\n")
        return 2

    records = []
    for model in models:
        records.append(bake_one(model, args))

    findings = write_findings(records, args.out)
    json.dump(findings, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
