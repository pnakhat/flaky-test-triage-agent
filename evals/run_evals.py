"""Step 9: score the agent against labelled historical failures.

    python evals/run_evals.py                 # offline judge (no API key needed)
    ANTHROPIC_API_KEY=... python evals/run_evals.py --judge claude

Exits non-zero when regression recall drops below the gate, so a prompt or
model change that starts waving real bugs through fails CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage import FailureEvent, TriageAgent, Verdict  # noqa: E402
from triage.judge import ClaudeJudge, OfflineJudge  # noqa: E402
from triage.policy import HIGH_CONFIDENCE  # noqa: E402

DATASET = Path(__file__).with_name("dataset.jsonl")
REGRESSION_RECALL_GATE = 0.75


def ratio(n: int, d: int) -> float | None:
    return n / d if d else None


def fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--judge", choices=["offline", "claude"], default="offline")
    p.add_argument("--gate", type=float, default=REGRESSION_RECALL_GATE)
    args = p.parse_args()

    judge = ClaudeJudge() if args.judge == "claude" else OfflineJudge()
    agent = TriageAgent(judge=judge)
    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]

    print(f"{'id':<7} {'expected':<12} {'got':<12} {'conf':>5}  {'by':<14} result")
    tp_reg = fn_reg = flake_called = flake_right = escalated = correct = 0
    for row in rows:
        expected = Verdict(row["expected"])
        r = agent.triage(FailureEvent.from_dict(row))
        got, conf = r.assessment.verdict, r.assessment.confidence
        is_escalated = got == Verdict.UNKNOWN or conf < HIGH_CONFIDENCE

        correct += got == expected
        escalated += is_escalated
        if expected == Verdict.REGRESSION:
            tp_reg += got == Verdict.REGRESSION
            fn_reg += got != Verdict.REGRESSION
        if got == Verdict.FLAKE:
            flake_called += 1
            flake_right += expected == Verdict.FLAKE

        mark = "ok" if got == expected else "MISS"
        if expected == Verdict.REGRESSION and got == Verdict.FLAKE:
            mark = "MISS  <- regression called a flake"
        print(f"{row['id']:<7} {expected.value:<12} {got.value:<12} {conf:>5.2f}  {r.assessment.decided_by:<14} {mark}")

    recall = ratio(tp_reg, tp_reg + fn_reg)
    print()
    print(f"Accuracy            {fmt(ratio(correct, len(rows)))}  ({correct}/{len(rows)})")
    print(f"Regression recall   {fmt(recall)}  ({tp_reg}/{tp_reg + fn_reg})   gate >= {args.gate:.0%}")
    print(f"Flake precision     {fmt(ratio(flake_right, flake_called))}  ({flake_right}/{flake_called})")
    print(f"Escalation rate     {fmt(ratio(escalated, len(rows)))}  ({escalated}/{len(rows)})")

    if recall is not None and recall < args.gate:
        print("\nFAIL: regression recall below gate")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
