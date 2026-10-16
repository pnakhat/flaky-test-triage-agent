# Flaky Test Triage Agent

A worked example of a **decision-making** quality engineering agent, written for *The Quality Signal* newsletter.

For every failed CI test, the agent decides: **regression, flake, environment fault or broken test?** Then it takes a bounded action. It does not generate tests. It removes the "rerun the pipeline and see" loop.

```
failed test
   │
   ▼
gather evidence ──► deterministic filter ──► clear? ──yes──► policy table ──► actions
 (history, diff,     (reruns + flake score)    │                 ▲             ├─ act alone: rerun, label, ticket, block PR, route to SRE
  logs, env)                                   no                │             ├─ propose (human approves): quarantine, fix PR
                                               ▼                 │             └─ escalate: low confidence
                                          LLM judgement ─────────┘
                                          (verdict, root cause,           human verdicts ──► eval set ──► scores every change
                                           confidence, evidence)
```

## Why this design

| Principle | Where it lives |
| --- | --- |
| **Own one decision**, not an artefact | `triage/agent.py` |
| **Read real evidence**: CI history, diff, reruns, env health | `triage/models.py` (`FailureEvent`) |
| **Deterministic first**: cheap rules settle clear cases, no LLM | `triage/filter.py` |
| **LLM for judgement only**, with forced structured output | `triage/judge.py` |
| **Authority is code, not prompt**: the model proposes, the policy decides | `triage/policy.py` |
| **Irreversible actions need a human**: quarantine and fix PRs are proposals | `triage/policy.py` |
| **Prove it with evals**: CI fails if regression recall drops | `evals/run_evals.py` |

## Quick start

No API key needed: without one, an offline keyword judge stands in for the LLM.

```bash
python -m triage examples/*.json      # triage three sample failures (dry run)
python evals/run_evals.py             # score against 12 labelled failures
pip install pytest && pytest -q       # unit tests for the guardrails
```

With Claude as the judge:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
export TRIAGE_MODEL=claude-sonnet-4-5   # any current Claude model
python -m triage examples/*.json
python evals/run_evals.py --judge claude
```

## Sample output

```
F-101  ->  REGRESSION  (confidence 0.90, decided by filter)
  evidence: Failed all 3 reruns on the same SHA
  evidence: Commit changes code the test exercises: src/checkout/voucher.py
  evidence: Test was stable before (flakiness score 0.09)
  action: label              143b685
  action: block_pr           143b685
  action: notify             team-checkout

F-102  ->  FLAKE  (confidence 0.99, decided by filter)
  evidence: Flipped pass/fail on the same SHA (2 of 3 reruns passed)
  evidence: Historical flakiness score 0.64
  action: label              9178912
  action: open_ticket        team-search
  action: propose_quarantine search/test_results.py::test_sort_by_price  [needs human]
```

## The eval, and why one miss is the point

```
F-110   regression   flake         0.70  offline-judge  MISS  <- regression called a flake

Accuracy            83%  (10/12)
Regression recall   80%  (4/5)   gate >= 75%
Flake precision     75%  (3/4)
Escalation rate     58%  (7/12)
```

`F-110` is a trap: a **performance regression** that surfaces as a timeout, so it looks exactly like a flaky test. The offline judge falls for it. That is the most expensive error a triage agent can make, which is why **regression recall** is the gate metric, not accuracy. Swap in Claude, tighten the prompt, add evidence (for example, page-load timings before and after the commit) and the eval tells you whether you fixed it without breaking anything else.

Add your own labelled failures to `evals/dataset.jsonl` from closed tickets. A few hundred real cases beat any demo.

## The ten steps, mapped to the code

1. **Decision and boundary**: verdict set in `models.Verdict`; authority list in `policy.py`.
2. **Baseline**: measure red builds, reruns and time-to-verdict for a month before switching anything on.
3. **Evidence**: `FailureEvent` fields. In production, fill them from your CI API, Git host and monitoring.
4. **Deterministic filter**: `filter.deterministic_filter` and `filter.flakiness_score` (Beta-prior flip rate).
5. **LLM judgement**: `judge.ClaudeJudge`, tool-use schema forces verdict, root cause, confidence, evidence.
6. **Policy table**: `policy.decide_actions`; confidence threshold `HIGH_CONFIDENCE = 0.8`.
7. **Fix proposals**: `fix_category` follows [FlakyFix](https://arxiv.org/abs/2307.00012): predict the category, then generate the patch.
8. **Quarantine without hiding bugs**: never for critical-path tests; quarantined tests keep running in a separate lane.
9. **Evals**: `evals/run_evals.py`, wired into CI with a regression-recall gate.
10. **Trust stages**: shadow → advise → act on reversible → propose irreversible. This repo is a dry run, i.e. stage 1.

## Wiring it into CI

`examples/github-workflow.yml` shows how to run the agent when a workflow fails and write the verdicts to the job summary. You supply a small adapter that turns your CI's test results into `FailureEvent` JSON.

## Root-cause taxonomy

`async_wait`, `concurrency`, `order_dependency`, `resource_leak`, `network`, `time`, `other`, from Luo et al., *An Empirical Analysis of Flaky Tests*, FSE 2014.

## References

- [Flaky Tests at Google and How We Mitigate Them](https://testing.googleblog.com/2016/05/), Google Testing Blog, 2016
- [Taming test flakiness](https://www.atlassian.com/blog/atlassian-engineering/taming-test-flakiness-how-we-built-a-scalable-tool-to-detect-and-manage-flaky-tests), Atlassian Engineering, 2025
- [FlakyFix: Using LLMs for Predicting Flaky Test Fix Categories and Test Code Repair](https://arxiv.org/abs/2307.00012), ICST 2025
- [Building effective agents](https://www.anthropic.com/research/building-effective-agents), Anthropic

## Licence

MIT. Example code for learning; not production-hardened.
