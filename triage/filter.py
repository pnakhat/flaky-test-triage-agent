"""Step 4: the deterministic filter. No LLM.

Cheap, repeatable rules settle the clear cases. Only what they cannot settle
goes to the LLM judge.
"""

from __future__ import annotations

from .models import Assessment, FailureEvent, Verdict


def flakiness_score(history: list[str]) -> float:
    """Posterior mean flip rate over the history window, Beta(1, 1) prior.

    A "flip" is a pass->fail or fail->pass transition between consecutive runs.
    A stable test scores near 0; a test that flips on every run scores near 1.
    Same idea as Atlassian's 0-to-1 flakiness score, kept deliberately simple.
    """
    if len(history) < 2:
        return 0.5  # no evidence either way
    transitions = len(history) - 1
    flips = sum(1 for a, b in zip(history, history[1:]) if a != b)
    return (flips + 1) / (transitions + 2)


def _flipped_on_same_sha(reruns: list[str]) -> bool:
    return "pass" in reruns and "fail" in reruns


def deterministic_filter(f: FailureEvent) -> Assessment | None:
    """Return an Assessment when the rules are conclusive, else None (send to the judge)."""
    score = flakiness_score(f.history)

    # Rule 1: infrastructure was unhealthy when the test failed.
    if not f.env_healthy:
        return Assessment(
            verdict=Verdict.ENVIRONMENT,
            confidence=0.95,
            evidence=["Environment health check was failing at the time of the run"],
            decided_by="filter",
            flakiness_score=score,
        )

    # Rule 2: same commit, different results. The code did not change, the outcome did.
    if _flipped_on_same_sha(f.reruns_same_sha):
        passes = f.reruns_same_sha.count("pass")
        return Assessment(
            verdict=Verdict.FLAKE,
            confidence=min(0.99, 0.75 + score / 2),
            evidence=[
                f"Flipped pass/fail on the same SHA ({passes} of {len(f.reruns_same_sha)} reruns passed)",
                f"Historical flakiness score {score:.2f}",
            ],
            decided_by="filter",
            flakiness_score=score,
        )

    all_failed = bool(f.reruns_same_sha) and all(r == "fail" for r in f.reruns_same_sha)
    touches_code_under_test = bool(set(f.diff_files) & set(f.test_imports))
    touches_test_only = f.test_file in f.diff_files and not touches_code_under_test

    # Rule 3: fails every time, and the commit changed code this test exercises.
    if all_failed and touches_code_under_test and score < 0.2:
        overlap = sorted(set(f.diff_files) & set(f.test_imports))
        return Assessment(
            verdict=Verdict.REGRESSION,
            confidence=0.9,
            evidence=[
                f"Failed all {len(f.reruns_same_sha)} reruns on the same SHA",
                f"Commit changes code the test exercises: {', '.join(overlap)}",
                f"Test was stable before (flakiness score {score:.2f})",
            ],
            decided_by="filter",
            flakiness_score=score,
        )

    # Rule 4: fails every time, and only the test file itself changed.
    if all_failed and touches_test_only:
        return Assessment(
            verdict=Verdict.BROKEN_TEST,
            confidence=0.85,
            evidence=[
                f"Failed all {len(f.reruns_same_sha)} reruns on the same SHA",
                "Commit changed the test file but no production code it exercises",
            ],
            decided_by="filter",
            flakiness_score=score,
        )

    return None  # ambiguous: hand to the judge
