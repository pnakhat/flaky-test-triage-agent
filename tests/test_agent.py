import json
from pathlib import Path

from triage import FailureEvent, TriageAgent, Verdict
from triage.filter import deterministic_filter, flakiness_score
from triage.judge import OfflineJudge
from triage.models import Assessment
from triage.policy import decide_actions

ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> FailureEvent:
    return FailureEvent.from_dict(json.loads((ROOT / "examples" / f"{name}.json").read_text()))


def test_flakiness_score_bounds():
    assert flakiness_score(["pass"] * 10) < 0.1
    assert flakiness_score(["pass", "fail"] * 5) > 0.8
    assert flakiness_score([]) == 0.5


def test_filter_settles_clear_regression():
    a = deterministic_filter(load("regression"))
    assert a and a.verdict == Verdict.REGRESSION and a.decided_by == "filter"


def test_filter_settles_flip_on_same_sha_as_flake():
    a = deterministic_filter(load("flake"))
    assert a and a.verdict == Verdict.FLAKE


def test_ambiguous_case_goes_to_judge():
    f = load("ambiguous-timeout")
    assert deterministic_filter(f) is None
    r = TriageAgent(judge=OfflineJudge()).triage(f)
    assert r.assessment.decided_by == "offline-judge"


def test_critical_path_flake_is_never_proposed_for_quarantine():
    f = load("flake")
    f.critical_path = True
    a = Assessment(Verdict.FLAKE, 0.95, ["flipped"], "filter", "async_wait", "handle_timeout")
    kinds = [x.kind for x in decide_actions(f, a)]
    assert "propose_quarantine" not in kinds


def test_irreversible_actions_always_need_a_human():
    f = load("flake")
    a = Assessment(Verdict.FLAKE, 0.95, ["flipped"], "filter", "async_wait", "handle_timeout")
    for act in decide_actions(f, a):
        if act.kind.startswith("propose_"):
            assert act.needs_human


def test_low_confidence_regression_escalates():
    f = load("regression")
    a = Assessment(Verdict.REGRESSION, 0.5, ["maybe"], "llm")
    acts = decide_actions(f, a)
    assert any(x.kind == "escalate" and x.needs_human for x in acts)
    assert any(x.kind == "block_pr" for x in acts)  # still blocks: cheap and reversible


def test_unknown_never_acts():
    f = load("regression")
    a = Assessment(Verdict.UNKNOWN, 0.0, ["no idea"], "offline-judge")
    acts = decide_actions(f, a)
    assert [x.kind for x in acts] == ["escalate"]
