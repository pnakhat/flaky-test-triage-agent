"""Step 6: the policy table. Code, not prompt.

The model proposes a verdict; this table alone decides what the agent may do.
Irreversible actions are only ever *proposed* (needs_human=True).
"""

from __future__ import annotations

from .models import Action, Assessment, FailureEvent, Verdict

HIGH_CONFIDENCE = 0.8


def decide_actions(f: FailureEvent, a: Assessment) -> list[Action]:
    high = a.confidence >= HIGH_CONFIDENCE
    why = "; ".join(a.evidence)

    if a.verdict == Verdict.REGRESSION:
        actions = [
            Action("label", f.sha, "triage:regression"),
            Action("block_pr", f.sha, f"Likely regression in {f.test}. Evidence: {why}"),
        ]
        actions.append(
            Action("notify", f.owner, "Regression flagged on your change", needs_human=False)
            if high
            else Action("escalate", f.owner, "Possible regression, low confidence: please confirm", needs_human=True)
        )
        return actions

    if a.verdict == Verdict.FLAKE:
        actions = [
            Action("label", f.sha, "triage:flake"),
            Action(
                "open_ticket",
                f.owner,
                f"Flaky test {f.test} (root cause: {a.root_cause or 'unknown'}, "
                f"suggested fix: {a.fix_category or 'investigate'}). Evidence: {why}",
            ),
        ]
        if high and not f.critical_path:
            actions.append(
                Action(
                    "propose_quarantine",
                    f.test,
                    "Move to quarantine lane; keeps running there and returns after a healthy period",
                    needs_human=True,
                )
            )
        if high and a.fix_category:
            actions.append(
                Action("propose_fix_pr", f.test, f"Draft fix PR using category '{a.fix_category}'", needs_human=True)
            )
        if not high:
            actions.append(Action("escalate", f.owner, "Flake suspected but not confirmed", needs_human=True))
        return actions

    if a.verdict == Verdict.ENVIRONMENT:
        actions = [
            Action("label", f.sha, "triage:environment"),
            Action("route", "platform-sre", f"Environment fault during {f.test}. Evidence: {why}"),
        ]
        if high:
            actions.append(Action("rerun", f.test, "Rerun automatically once environment is healthy"))
        return actions

    if a.verdict == Verdict.BROKEN_TEST:
        return [
            Action("label", f.sha, "triage:broken-test"),
            Action("open_ticket", f.owner, f"Test {f.test} needs updating. Evidence: {why}"),
        ]

    # Unknown or anything unexpected: never act, always hand to a human.
    return [Action("escalate", f.owner, "Agent could not classify this failure", needs_human=True)]
