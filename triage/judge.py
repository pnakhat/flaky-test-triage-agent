"""Step 5: LLM judgement for the ambiguous cases only.

Two judges share one interface:

* ClaudeJudge   - calls the Anthropic API with forced structured output (tool use).
* OfflineJudge  - keyword heuristics, so the demo and the eval suite run with no
                  API key. It is a stand-in, not a recommendation.
"""

from __future__ import annotations

import json
import os
import re

from .filter import flakiness_score
from .models import ROOT_CAUSES, Assessment, FailureEvent, Verdict

SYSTEM_PROMPT = """You are a test-failure triage analyst for a CI pipeline.
Classify ONE failed test using only the evidence given. Do not guess beyond it.

Verdicts:
- regression: the product code changed and now behaves wrongly.
- flake: the test is non-deterministic; the code under test is probably fine.
- environment: infrastructure, network or a dependency failed, not the code or test.
- broken_test: the test itself is wrong or out of date.

Rules:
- Calling a real regression a flake is the most expensive mistake. If a regression
  is plausible, say so and lower your confidence rather than calling it a flake.
- Cite concrete evidence lines (from the error, diff, history or reruns).
- Confidence is your probability that the verdict is right, 0 to 1.
"""

VERDICT_TOOL = {
    "name": "record_verdict",
    "description": "Record the triage verdict for this failed test.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": [v.value for v in Verdict if v != Verdict.UNKNOWN]},
            "root_cause": {"type": "string", "enum": list(ROOT_CAUSES)},
            "fix_category": {
                "type": "string",
                "description": "FlakyFix-style fix category, e.g. handle_timeout, reorder_data, "
                "reset_variable, change_assertion, change_condition, handle_exception.",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["verdict", "root_cause", "confidence", "evidence"],
    },
}


def build_prompt(f: FailureEvent) -> str:
    return json.dumps(
        {
            "test": f.test,
            "error": f.error,
            "history_on_main_oldest_first": f.history,
            "flakiness_score": round(flakiness_score(f.history), 2),
            "reruns_on_failing_sha": f.reruns_same_sha,
            "files_changed_by_commit": f.diff_files,
            "test_file": f.test_file,
            "production_files_test_exercises": f.test_imports,
            "environment_healthy": f.env_healthy,
        },
        indent=2,
    )


class ClaudeJudge:
    name = "llm"

    def __init__(self, model: str | None = None):
        import anthropic  # imported lazily so the offline path needs no dependency

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("TRIAGE_MODEL", "claude-sonnet-4-5")

    def assess(self, f: FailureEvent) -> Assessment:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=800,
            system=SYSTEM_PROMPT,
            tools=[VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "record_verdict"},
            messages=[{"role": "user", "content": build_prompt(f)}],
        )
        out = next(b.input for b in msg.content if b.type == "tool_use")
        return Assessment(
            verdict=Verdict(out["verdict"]),
            confidence=float(out["confidence"]),
            evidence=list(out["evidence"]),
            decided_by=self.name,
            root_cause=out.get("root_cause"),
            fix_category=out.get("fix_category"),
            flakiness_score=flakiness_score(f.history),
        )


# (pattern, verdict, root_cause, fix_category, confidence)
_RULES = [
    (r"timeout|timed out|not clickable|waiting for|stale element", Verdict.FLAKE, "async_wait", "handle_timeout", 0.7),
    (r"deadlock|race|concurrent|lock wait", Verdict.FLAKE, "concurrency", "change_condition", 0.65),
    (r"connection (refused|reset)|econnreset|dns|503|502|bad gateway", Verdict.ENVIRONMENT, "network", None, 0.7),
    (r"already exists|duplicate key|unique constraint|leftover", Verdict.FLAKE, "order_dependency", "reset_variable", 0.6),
    (r"too many open files|out of memory|oom", Verdict.ENVIRONMENT, "resource_leak", None, 0.6),
    (r"timezone|utc|daylight|clock", Verdict.FLAKE, "time", "change_timezone", 0.6),
    (r"assert(ion)?error|expected .* (but )?(got|was)", Verdict.REGRESSION, "other", None, 0.55),
]


class OfflineJudge:
    """Keyword stand-in for the LLM. Deliberately humble: low confidence means escalation."""

    name = "offline-judge"

    def assess(self, f: FailureEvent) -> Assessment:
        err = f.error.lower()
        for pattern, verdict, cause, fix, conf in _RULES:
            if re.search(pattern, err):
                return Assessment(
                    verdict=verdict,
                    confidence=conf,
                    evidence=[f"Error message matches '{pattern.split('|')[0]}' pattern: {f.error[:120]}"],
                    decided_by=self.name,
                    root_cause=cause,
                    fix_category=fix,
                    flakiness_score=flakiness_score(f.history),
                )
        return Assessment(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            evidence=["No rule matched; needs a human"],
            decided_by=self.name,
            flakiness_score=flakiness_score(f.history),
        )


def default_judge():
    """Use Claude when a key is configured, otherwise the offline stand-in."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return ClaudeJudge()
        except ImportError:
            pass
    return OfflineJudge()
