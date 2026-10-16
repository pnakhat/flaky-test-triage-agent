"""The agent loop: evidence -> filter -> judge (if needed) -> policy -> actions."""

from __future__ import annotations

from .filter import deterministic_filter
from .judge import default_judge
from .models import FailureEvent, TriageResult
from .policy import decide_actions


class TriageAgent:
    def __init__(self, judge=None):
        self.judge = judge or default_judge()

    def triage(self, f: FailureEvent) -> TriageResult:
        assessment = deterministic_filter(f)          # Step 4: cheap rules first
        if assessment is None:
            assessment = self.judge.assess(f)         # Step 5: LLM only for ambiguous cases
        actions = decide_actions(f, assessment)       # Step 6: coded policy decides what happens
        return TriageResult(failure_id=f.id, assessment=assessment, actions=actions)
