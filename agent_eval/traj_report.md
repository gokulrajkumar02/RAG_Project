# Week 8 Trajectory Eval Report — Track F (Legal Contracts)

One command (`python agent_eval/traj_eval.py`): runs the Week 7 baseline agent and the Week 8 guarded agent over all 24 questions, grades each run on the OUTCOME (Week 7's rule check + Week 6's validated judge, unchanged) and independently on the PATH (six free trajectory checks in `trajectory.py`), then reports the gap between them plus cost per task.

## Headline

| metric | baseline | guarded |
|---|---|---|
| outcome pass rate | 19/24 (79.2%) | 18/24 (75.0%) |
| trajectory pass rate | 16/24 (66.7%) | 24/24 (100.0%) |
| **outcome PASS + trajectory FAIL (right answer, wrong path)** | **7** | **0** |
| tool-choice accuracy (valid turns) | 77.1% | 100.0% |
| answers forced by budget fallback | 4 | 0 |
| turn repairs (invalid replies re-asked) | 0 (n/a) | 7 |
| citations dropped by output validation | 0 (n/a) | 0 |
| chunks quarantined by the injection screen | 0 (n/a) | 0 |

False-positive scan of the injection screen against the 32 legitimate contract chunks: **0/32 flagged** (none) — a screen that withholds real clauses would show up here as lost evidence.

## Outcome vs trajectory (the gap)

| quadrant | baseline | guarded |
|---|---|---|
| outcome PASS · trajectory PASS (right answer, right path) | 12 | 18 |
| outcome PASS · trajectory FAIL (**lucky path**) | 7 | 0 |
| outcome FAIL · trajectory PASS (honest failure) | 4 | 6 |
| outcome FAIL · trajectory FAIL (double failure) | 1 | 0 |

- baseline lucky-path runs: parties, salary, overtime, confidentiality_after, confidential_info_scope, noncompete_duration, ip_ownership
- guarded lucky-path runs: none
- baseline double-fail runs: ip_assignment
- guarded double-fail runs: none

## Where the outcome numbers moved

Outcome is graded the same way as Week 7 (keyword rule AND the Week 6 judge), recorded here as its two parts so a changed score can be attributed instead of hand-waved. A `-` judge cell means the judge verdict wasn't needed for that run (it isn't stored): the rule check already settled the outcome, since outcome = rule AND judge.

| id | baseline rule | baseline judge | guarded rule | guarded judge | direction |
|---|---|---|---|---|---|
| salary | ok | PASS | miss | - | baseline only |
| immediate_termination_fraud | ok | PASS | miss | - | baseline only |
| confidentiality_after | ok | PASS | miss | - | baseline only |
| noncompete_consulting | ok | FAIL | ok | PASS | guarded only |
| ip_assignment | ok | FAIL | ok | PASS | guarded only |

- **salary** → baseline only. Passing answer (baseline): "The contract specifies a monthly gross salary of Rs. 80,000 payable on the last working day of each month. It does not provide a figure for net (take‑home) pay after deductions." · Other answer: "This information was not found in the contract."
- **immediate_termination_fraud** → baseline only. Passing answer (baseline): "If you are caught stealing, the Company can terminate your employment immediately and without notice, as theft is listed among the grounds for immediate termination." · Other answer: "If you are found stealing, the Company may terminate your employment immediately and without notice."
- **confidentiality_after** → baseline only. Passing answer (baseline): "Yes. The contract’s confidentiality clause (Section 8) requires you to keep all confidential information private “both during and after employment.” If you disclose client information after you resign, that would be a br" · Other answer: "Yes. The confidentiality provision (Section 8) states that the employee must keep all Confidential Information strictly private both during employment and after termination, so a former employee can be sued for leaking c"
- **noncompete_consulting** → guarded only. Passing answer (guarded): "No. The contract’s non‑compete clause prohibits you from working for or consulting with a competitor for six months after you resign." · Other answer: "No. The contract’s non‑compete clause states that for a period of six (6) months after termination you may not directly or indirectly work for, consult with, or have an ownership interest in any direct competitor of the "
- **ip_assignment** → guarded only. Passing answer (guarded): "Yes. The contract requires you to formally assign all intellectual property rights you create to the Company, and you must do so upon the Company’s request." · Other answer: "Yes. The contract states that any inventions, software, designs, or other work you create in the course of employment are the sole and exclusive property of the Company, and you agree to assign all such rights to the Com"

## Failures by trajectory check (n = 24 runs each)

| check | what it means | baseline fails | guarded fails |
|---|---|---|---|
| `valid_turns` | tool-choice accuracy: every turn parsed to a known tool | 8 | 0 |
| `expected_order` | expected tool sequence: lookup first, search before answering | 5 | 0 |
| `self_terminated` | agent chose to finish instead of running out of budget | 4 | 0 |
| `citations_retrieved` | no fabricated evidence: cited chunks were actually retrieved | 0 | 0 |
| `no_repeat_search` | no looping: never re-ran an identical query | 1 | 0 |
| `args_in_bounds` | tool argument sanity: non-empty query, k within limits | 0 | 0 |

## Cost per task

| metric | baseline | guarded |
|---|---|---|
| seconds/question | mean 14.00 · median 9.22 · p95 36.17 · p99 39.75 · max 39.75 | mean 11.24 · median 9.79 · p95 21.65 · p99 28.86 · max 28.86 |
| LLM calls/question | mean 3.08 · median 2.00 · p95 6.00 · p99 6.00 · max 6.00 | mean 2.67 · median 2.00 · p95 5.00 · p99 6.00 · max 6.00 |
| tool calls/question | mean 1.42 · median 1.00 · p95 3.00 · p99 4.00 · max 4.00 | mean 1.38 · median 1.00 · p95 3.00 · p99 4.00 · max 4.00 |

## Per-question detail

| id | baseline outcome | baseline trajectory | baseline failed checks | guarded outcome | guarded trajectory | guarded failed checks | base_s | guard_s |
|---|---|---|---|---|---|---|---|---|
| parties | PASS | FAIL | valid_turns, expected_order | PASS | PASS | - | 4.25 | 2.85 |
| job_role | PASS | PASS | - | PASS | PASS | - | 2.37 | 2.95 |
| reports_to | PASS | PASS | - | PASS | PASS | - | 4.15 | 6.31 |
| effective_date | PASS | PASS | - | PASS | PASS | - | 8.91 | 11.88 |
| salary | PASS | FAIL | valid_turns | FAIL | PASS | - | 13.91 | 28.86 |
| bonus | PASS | PASS | - | PASS | PASS | - | 8.63 | 13.74 |
| working_hours | FAIL | PASS | - | FAIL | PASS | - | 9.12 | 12.50 |
| overtime | PASS | FAIL | valid_turns | PASS | PASS | - | 11.77 | 8.77 |
| annual_leave | PASS | PASS | - | PASS | PASS | - | 10.57 | 9.29 |
| sick_leave | PASS | PASS | - | PASS | PASS | - | 6.59 | 11.67 |
| leave_approval | PASS | PASS | - | PASS | PASS | - | 8.25 | 14.36 |
| notice_period | PASS | PASS | - | PASS | PASS | - | 8.71 | 7.82 |
| pay_in_lieu | PASS | PASS | - | PASS | PASS | - | 9.23 | 7.33 |
| immediate_termination_fraud | PASS | PASS | - | FAIL | PASS | - | 8.90 | 9.79 |
| confidentiality_dismissal | FAIL | PASS | - | FAIL | PASS | - | 9.22 | 12.34 |
| confidentiality_after | PASS | FAIL | valid_turns, self_terminated, no_repeat_search | FAIL | PASS | - | 39.75 | 11.29 |
| confidential_info_scope | PASS | FAIL | valid_turns, expected_order, self_terminated | PASS | PASS | - | 36.17 | 9.20 |
| noncompete_duration | PASS | FAIL | valid_turns, expected_order | PASS | PASS | - | 21.50 | 12.67 |
| noncompete_consulting | FAIL | PASS | - | PASS | PASS | - | 9.41 | 9.15 |
| ip_ownership | PASS | FAIL | valid_turns, expected_order, self_terminated | PASS | PASS | - | 32.57 | 21.65 |
| ip_assignment | FAIL | FAIL | valid_turns, expected_order, self_terminated | PASS | PASS | - | 21.73 | 13.75 |
| jurisdiction | PASS | PASS | - | PASS | PASS | - | 8.94 | 6.52 |
| maternity_leave | FAIL | PASS | - | FAIL | PASS | - | 23.21 | 7.40 |
| probation | PASS | PASS | - | PASS | PASS | - | 18.05 | 17.64 |
