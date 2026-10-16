"""Data shapes the agent passes between steps."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum


class Verdict(str, Enum):
    REGRESSION = "regression"
    FLAKE = "flake"
    ENVIRONMENT = "environment"
    BROKEN_TEST = "broken_test"
    UNKNOWN = "unknown"


# Root-cause taxonomy from Luo et al., FSE 2014 ("An Empirical Analysis of Flaky Tests").
ROOT_CAUSES = (
    "async_wait",
    "concurrency",
    "order_dependency",
    "resource_leak",
    "network",
    "time",
    "other",
)


@dataclass
class FailureEvent:
    """Everything the agent is allowed to look at for one failed test (Step 3: the evidence)."""

    id: str
    test: str
    sha: str
    error: str
    history: list[str]            # last N results on main, oldest first: "pass" | "fail"
    reruns_same_sha: list[str]    # results of reruns on the failing commit
    diff_files: list[str]         # files changed by the failing commit
    test_file: str                # path of the test itself
    test_imports: list[str]       # production files the test exercises
    critical_path: bool = False   # critical-path tests are never proposed for quarantine
    env_healthy: bool = True      # infra / dependency health at failure time
    owner: str = "unowned"

    @classmethod
    def from_dict(cls, d: dict) -> "FailureEvent":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


@dataclass
class Assessment:
    """A verdict with its confidence and the evidence behind it (Step 5 output shape)."""

    verdict: Verdict
    confidence: float
    evidence: list[str]
    decided_by: str                       # "filter" | "llm" | "offline-judge"
    root_cause: str | None = None
    fix_category: str | None = None
    flakiness_score: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d


@dataclass
class Action:
    kind: str                 # e.g. "rerun", "label", "open_ticket", "block_pr", "propose_quarantine"
    target: str
    detail: str
    needs_human: bool = False


@dataclass
class TriageResult:
    failure_id: str
    assessment: Assessment
    actions: list[Action] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "failure_id": self.failure_id,
            "assessment": self.assessment.to_dict(),
            "actions": [asdict(a) for a in self.actions],
        }
