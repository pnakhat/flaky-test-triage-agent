"""CLI: python -m triage examples/*.json [--json]

Dry run only. It prints the verdict and the actions the agent *would* take.
Wire the actions to your CI, Git host and ticketing system yourself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import TriageAgent
from .models import FailureEvent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="triage", description="Triage failed CI tests (dry run).")
    p.add_argument("files", nargs="+", type=Path, help="Failure event JSON files")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of a readable summary")
    args = p.parse_args(argv)

    agent = TriageAgent()
    results = [agent.triage(FailureEvent.from_dict(json.loads(path.read_text()))) for path in args.files]

    if args.json:
        json.dump([r.to_dict() for r in results], sys.stdout, indent=2)
        print()
        return 0

    for r in results:
        a = r.assessment
        print(f"\n{r.failure_id}  ->  {a.verdict.value.upper()}  (confidence {a.confidence:.2f}, decided by {a.decided_by})")
        if a.root_cause:
            print(f"  root cause: {a.root_cause}   fix category: {a.fix_category or '-'}")
        for e in a.evidence:
            print(f"  evidence: {e}")
        for act in r.actions:
            flag = "  [needs human]" if act.needs_human else ""
            print(f"  action: {act.kind:<18} {act.target}{flag}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
